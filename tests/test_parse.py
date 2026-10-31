"""Tests for anon.parse (normalized records) and anon.sources (download).

Real-corpus tests skip when data/ is absent (it is never committed); the synthetic
tests build their own source tree, so they always run.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import httpx
import pytest

from anon import parse
from anon.parse import corpus_counts, load_corpus, public_view
from anon.sources import FetchError, fetch_all

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample"
REAL = ROOT / "data" / "fuentes" / "raw"

SCHEMA = {
    "chats": ["id", "thread_id", "author", "ts", "text", "attachments"],
    "docs": ["id", "format", "filename", "title", "body", "metadata"],
    "tables": ["id", "table", "columns"],
}

needs_sample = pytest.mark.skipif(not (SAMPLE / "input").is_dir(), reason="no data/sample")
needs_real = pytest.mark.skipif(not REAL.is_dir(), reason="no data/fuentes/raw")


@pytest.fixture(scope="module")
def sample():
    return load_corpus(SAMPLE / "input")


@pytest.fixture(scope="module")
def real():
    return load_corpus(REAL)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


NO_ID_ISSUE = "chats: message without client_msg_id in soporte/2026-08-01.json (ts=102.000100)"


def _assert_matches_index(corpus, issues: list[str] | None = None) -> None:
    assert corpus.record_index is not None
    for source in parse.SOURCES:
        ids = [r["id"] for r in getattr(corpus, source)]
        assert len(ids) == len(set(ids)), f"{source}: duplicate ids"
        assert set(ids) == set(corpus.record_index[source]), f"{source}: ids != record_index"
    assert not [r for s in parse.SOURCES for r in getattr(corpus, s) if r.get("_placeholder")]
    assert corpus.issues == (issues or [])


def _assert_schema(corpus) -> None:
    for source, keys in SCHEMA.items():
        for rec in getattr(corpus, source):
            assert list(public_view(rec)) == keys, (source, rec["id"])
    for rec in corpus.chats:
        assert all(isinstance(rec[k], str) for k in ("id", "thread_id", "author", "ts", "text"))
        assert isinstance(rec["attachments"], list)
        assert all(list(a) == ["filename"] and isinstance(a["filename"], str)
                   for a in rec["attachments"])
        assert rec["thread_id"].startswith(f"{rec['_channel']}:")
        assert isinstance(rec["_is_bot"], bool)
    for rec in corpus.docs:
        assert rec["format"] in ("pdf", "html", "md")
        assert isinstance(rec["metadata"], dict)
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in rec["metadata"].items())
        assert rec["title"].strip() and isinstance(rec["body"], str)
    for rec in corpus.tables:
        assert rec["id"].startswith(f"{rec['table']}:")
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in rec["columns"].items())


# ------------------------------------------------------------------ sample data


@needs_sample
def test_sample_ids_match_record_index(sample):
    _assert_matches_index(sample)
    assert corpus_counts(sample) == {"chats": 10, "docs": 1, "tables": 4}


@needs_sample
def test_sample_schema(sample):
    _assert_schema(sample)


@needs_sample
def test_sample_chats_shape_matches_expected(sample):
    expected = {r["id"]: r for r in _read_jsonl(SAMPLE / "expected_output" / "chats.jsonl")}
    for rec in sample.chats:
        exp = expected[rec["id"]]
        out = public_view(rec)
        assert list(out) == list(exp)
        assert out["thread_id"] == exp["thread_id"]  # "<canal>:<ts of first message>"
        assert out["ts"] == exp["ts"]
        assert len(out["attachments"]) == len(exp["attachments"])
        assert [list(a) for a in out["attachments"]] == [list(a) for a in exp["attachments"]]
        assert out["author"] and not re.fullmatch(r"U[A-Z0-9]{6,}", out["author"])
    bot = next(r for r in sample.chats if r["_is_bot"])
    assert bot["author"] == "Kipi" and bot["_user"] == "UKIPIBOT01"
    client = next(r for r in sample.chats if r["_user"] == "U0V6WYVYG")
    users = json.loads((SAMPLE / "input" / "chats" / "users.json").read_text(encoding="utf-8"))
    real_name = next(u["real_name"] for u in users if u["id"] == "U0V6WYVYG")
    assert client["author"] == real_name  # the real name; the anonymizer maps it
    files = [a["filename"] for r in sample.chats for a in r["attachments"]]
    assert len(files) == 1 and re.fullmatch(r"extracto_[a-z_]+_julio\.pdf", files[0])


@needs_sample
def test_sample_md_keeps_front_matter(sample):
    doc = sample.docs[0]
    original = (SAMPLE / "input" / "docs" / "memo_cierre_julio.md").read_text(encoding="utf-8")
    assert doc["body"] == original
    assert doc["body"].startswith("---\ntitle: Memo cierre de julio 2026\n")
    exp = _read_jsonl(SAMPLE / "expected_output" / "docs.jsonl")[0]
    assert list(doc["metadata"]) == list(exp["metadata"])
    assert doc["metadata"]["fecha"] == exp["metadata"]["fecha"] == "2026-08-01"
    assert doc["metadata"]["title"] == exp["metadata"]["title"]
    assert re.fullmatch(r"[a-z]+\.[a-z]+@kipupay\.co", doc["metadata"]["author"])  # a staff e-mail


@needs_sample
def test_sample_tables_match_expected_columns(sample):
    expected = {r["id"]: r for r in _read_jsonl(SAMPLE / "expected_output" / "tables.jsonl")}
    for rec in sample.tables:
        exp = expected[rec["id"]]
        assert rec["table"] == exp["table"]
        assert list(rec["columns"]) == list(exp["columns"])
        # Columns the ideal output leaves untouched must come through identical.
        for col in ("cliente_id", "tipo_doc", "ciudad", "fecha_vinculacion"):
            assert rec["columns"][col] == exp["columns"][col]
    row = next(r for r in sample.tables if r["id"] == "clientes:CL-88627")
    client = next(r["author"] for r in sample.chats if r["_user"] == "U0V6WYVYG")
    assert row["columns"]["nombre_completo"] == client  # Latin-1 CSV decoded like the UTF-8 chats
    assert row["columns"]["notas"] == "Pago PSE aplicado con retraso en julio 2026; cobro retirado."
    empty_notes = next(r for r in sample.tables if r["id"] == "clientes:CL-92356")
    assert empty_notes["columns"]["notas"] == ""


# -------------------------------------------------------------------- real data


@needs_real
def test_real_ids_match_record_index(real):
    _assert_matches_index(real)
    assert corpus_counts(real) == {"chats": 2028, "docs": 26, "tables": 6243}


@needs_real
def test_real_schema(real):
    _assert_schema(real)
    assert all(d["body"].strip() for d in real.docs)


@needs_real
def test_real_html_bodies_keep_comments_and_hidden_text(real):
    html_docs = [d for d in real.docs if d["format"] == "html"]
    assert len(html_docs) == 6
    n_comments = 0
    for doc in html_docs:
        source = (REAL / "docs" / doc["filename"]).read_text(encoding="utf-8")
        for comment in re.findall(r"<!--.*?-->", source, re.S):
            assert comment in doc["body"], (doc["id"], comment)
            n_comments += 1
        for href in re.findall(r'href="mailto:([^"]+)"', source):
            assert href in doc["body"]
        assert "<style" not in doc["body"] and "font-family" not in doc["body"]
        assert doc["metadata"]["author"]
    assert n_comments == 3
    faq = next(d for d in html_docs if d["filename"] == "faq_clientes.html")
    assert re.search(r"Borrador revisado por \w+ \w+", faq["body"])  # display:none div


@needs_real
def test_real_md_bodies_are_the_original_text(real):
    for doc in (d for d in real.docs if d["format"] == "md"):
        assert doc["body"] == (REAL / "docs" / doc["filename"]).read_text(encoding="utf-8")
    acta = next(d for d in real.docs if d["filename"] == "acta_comite_fraude_2026-10-09.md")
    assert re.fullmatch(r"@[a-z]+\.[a-z]+(, @[a-z]+\.[a-z]+){2}", acta["metadata"]["asistentes"])
    assert acta["title"].startswith("Acta del comité de fraude")  # no FM title -> H1
    manual = next(d for d in real.docs if d["filename"] == "manual_onboarding_agentes.md")
    assert manual["metadata"]["version"] == "2.3"


@needs_real
def test_real_pdf_metadata_and_text(real):
    pdfs = {d["filename"]: d for d in real.docs if d["format"] == "pdf"}
    assert len(pdfs) == 11
    for doc in pdfs.values():
        assert "author" in doc["metadata"] and "title" in doc["metadata"]
        assert all(k == k.lower() and not k.startswith("/") for k in doc["metadata"])
    kp022 = pdfs["evaluacion_desempeno_KP-022_2026.pdf"]["metadata"]
    assert kp022["keywords"].endswith(", soporte, Cali, evaluación 2026") and kp022["keywords"].count(",") == 3
    agosto = pdfs["informe_pqr_agosto_2026.pdf"]["body"]
    assert "menos efectivo" in agosto and "menosefectivo" not in agosto  # wrapped cell
    assert re.search(r"\| PQR-2026-0540 \| [^|]+ \| Cajero entregó menos efectivo \| Cerrado \|", agosto)
    carta_name = next(name for name in pdfs if name.startswith("carta_cobro_juridico_"))
    carta = pdfs[carta_name]["body"]
    folded = unicodedata.normalize("NFKD", carta).encode("ascii", "ignore").decode().lower()
    debtor = carta_name.removeprefix("carta_cobro_juridico_").removesuffix(".pdf").split("_")
    assert all(part in folded for part in debtor)  # the debtor named in the file name
    assert re.search(r"CC \d{1,3}(?:\.\d{3}){2}", carta) and re.search(r"[\w.]+@gmail\.com", carta)


@needs_real
def test_real_tables(real):
    by_id = {r["id"]: r for r in real.tables}
    cli = by_id["clientes:CL-12538"]["columns"]
    assert re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+( [A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){2,3}", cli["nombre_completo"])  # Latin-1
    assert list(cli)[0] == "cliente_id" and len(cli) == 13
    assert ";" in by_id["clientes:CL-19774"]["columns"]["notas"]  # quoted separator kept
    tx = by_id["transacciones:TX-000158"]["columns"]
    assert list(tx) == ["tx_id", "fecha", "cliente_id", "tipo", "monto", "descripcion",
                        "canal", "estado"]
    pqr = by_id["pqrs:PQR-2026-0451"]["columns"]
    assert re.fullmatch(r"[a-z]+\.[a-z]+", pqr["agente"])
    assert pqr["descripcion"].startswith("Me cobraron 356.000")  # CDATA text
    emp = by_id["empleados:KP-005"]["columns"]
    staff = [r["columns"]["nombre"] for r in real.tables if r["table"] == "empleados"]
    assert any(name.startswith(emp["reporta_a"]) for name in staff)  # reports to a colleague
    assert emp["documento_tipo"] == "CC"
    assert list(emp) == ["id", "cargo", "ciudad", "ingreso", "reporta_a", "nombre",
                         "correo", "celular", "documento", "documento_tipo",
                         "fecha_nacimiento"]


@needs_real
def test_real_chats_details(real):
    users = real.users
    assert real.chats[0]["thread_id"].count(":") == 1
    for rec in real.chats:
        user = users.get(rec["_user"]) or {}
        if user.get("real_name"):
            assert rec["author"] == user["real_name"]
    deleted = [r for r in real.chats if r["_deleted_user"]]
    assert deleted and all(r["author"] == "deactivateduser" for r in deleted)
    mentions = [m for r in real.chats for m in r["_mentions"]]
    assert len(mentions) == 10 and all(m in users for m in mentions)
    assert sum(len(r["attachments"]) for r in real.chats) == 36
    threads = {r["thread_id"] for r in real.chats}
    assert len(threads) == 320


# ------------------------------------------------------------ synthetic sources


def test_front_matter_keeps_original_strings():
    meta = parse._parse_front_matter([
        "title: Acta: comité de crédito",
        "date: 2026-08-28",
        "version: 2.3",
        "revisado_por: @renata.molina",
        'quoted: "Hola, mundo"',
        "tags:",
        "  - riesgo",
        "  - cobranza",
        "url: https://www.loom.com/share/x",
    ])
    assert meta == {
        "title": "Acta: comité de crédito", "date": "2026-08-28", "version": "2.3",
        "revisado_por": "@renata.molina", "quoted": "Hola, mundo",
        "tags": "riesgo, cobranza", "url": "https://www.loom.com/share/x",
    }


def _make_pdf() -> bytes:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_metadata({"/Title": "Carta", "/Author": "Ana Benítez", "/Keywords": "a, b"})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _build_sources(root: Path) -> dict[str, bytes]:
    """A tiny source tree (layout of fetch_all) as {relative path: bytes}."""
    msgs_a = [
        {"type": "message", "user": "U1", "text": "Hola <@U2>", "ts": "100.000100",
         "client_msg_id": "m1", "files": [{"id": "F1", "name": "extracto_ana_benitez.pdf"}]},
        {"type": "message", "user": "UBOT", "text": "Soy Kipi", "ts": "101.000100",
         "client_msg_id": "m2", "thread_ts": "100.000100", "subtype": "bot_message",
         "username": "Kipi"},
        {"type": "message", "subtype": "channel_join", "user": "U2", "text": "joined",
         "ts": "102.000100"},  # no client_msg_id: not a record
    ]
    msgs_b = [{"type": "message", "user": "U2", "text": "Listo", "ts": "200.000100",
               "client_msg_id": "m3", "thread_ts": "100.000100"}]
    files = {
        "chats/channels.json": json.dumps([{"id": "C1", "name": "soporte"}]).encode(),
        "chats/users.json": json.dumps([
            {"id": "U1", "name": "ana", "real_name": "Ana Benítez", "profile": {}},
            {"id": "U2", "name": "luis.r", "real_name": "", "profile": {"real_name": "Luis R"}},
            {"id": "UBOT", "name": "kipi", "real_name": "Kipi", "is_bot": True, "profile": {}},
        ]).encode(),
        "chats/soporte/2026-08-01.json": json.dumps(msgs_a, ensure_ascii=False).encode(),
        "chats/soporte/2026-08-02.json": json.dumps(msgs_b).encode(),
        "docs/index.json": json.dumps([
            {"id": "d1", "filename": "memo.md", "format": "md"},
            {"id": "d2", "filename": "pagina.html", "format": "html"},
            {"id": "d3", "filename": "carta.pdf", "format": "pdf"},
        ]).encode(),
        "docs/memo.md": b"---\ntitle: Memo\nauthor: ana@x.co\n---\n# Memo\n\nTexto.\n",
        "docs/pagina.html": (
            "<html><head><title>Página</title><meta name='author' content='Luis R'>"
            "<!-- head: luis@x.co --></head><body><h1>Hola</h1><p>Uno *dos* tres_cuatro</p>"
            "<!-- body: ana@x.co --></body></html>").encode(),
        "docs/carta.pdf": _make_pdf(),
        "tables/index.json": json.dumps([
            {"name": "clientes.csv", "format": "csv", "charset": "latin-1", "separator": ";"},
            {"name": "empleados.xml", "format": "xml", "charset": "utf-8"},
        ]).encode(),
        "tables/clientes.csv": (
            'cliente_id;nombre_completo;notas\r\nCL-1;Ana Muñoz;"uno; dos"\r\nCL-2;Luis R;\r\n'
        ).encode("latin-1"),
        "tables/empleados.xml": (
            '<?xml version="1.0" encoding="UTF-8"?><empleados>'
            '<empleado id="KP-1" reporta_a="Ana Benítez"><nombre>Luis R</nombre>'
            '<documento tipo="CC">123</documento><nota><![CDATA[a <b> c]]></nota></empleado>'
            '</empleados>').encode(),
        "record_index.json": json.dumps({
            "chats": ["m1", "m2", "m3"], "docs": ["d1", "d2", "d3"],
            "tables": ["clientes:CL-1", "clientes:CL-2", "empleados:KP-1"]}).encode(),
        "tests_public.json": b"[]",
    }
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return files


def test_synthetic_corpus(tmp_path):
    _build_sources(tmp_path)
    corpus = load_corpus(tmp_path)
    _assert_matches_index(corpus, [NO_ID_ISSUE])  # the channel_join message
    _assert_schema(corpus)
    chats = {r["id"]: r for r in corpus.chats}
    assert chats["m1"]["thread_id"] == "soporte:100.000100"
    assert chats["m3"]["thread_id"] == "soporte:100.000100"  # reply on another day
    assert chats["m1"]["attachments"] == [{"filename": "extracto_ana_benitez.pdf"}]
    assert chats["m1"]["_mentions"] == ["U2"]
    assert chats["m2"]["author"] == "Kipi" and chats["m2"]["_is_bot"]
    assert chats["m3"]["author"] == "Luis R"  # profile.real_name fallback
    docs = {r["id"]: r for r in corpus.docs}
    html = docs["d2"]
    assert "<!-- head: luis@x.co -->" in html["body"] and "<!-- body: ana@x.co -->" in html["body"]
    assert "*dos* tres_cuatro" in html["body"]  # no markdown escaping
    assert html["metadata"]["author"] == "Luis R" and html["title"] == "Página"
    pdf = docs["d3"]
    assert pdf["metadata"]["author"] == "Ana Benítez" and pdf["metadata"]["keywords"] == "a, b"
    assert pdf["title"] == "Carta"
    tables = {r["id"]: r["columns"] for r in corpus.tables}
    assert tables["clientes:CL-1"] == {"cliente_id": "CL-1", "nombre_completo": "Ana Muñoz",
                                       "notas": "uno; dos"}
    assert tables["clientes:CL-2"]["notas"] == ""
    assert tables["empleados:KP-1"] == {"id": "KP-1", "reporta_a": "Ana Benítez",
                                        "nombre": "Luis R", "documento": "123",
                                        "documento_tipo": "CC", "nota": "a <b> c"}


def test_reconcile_drops_extras_and_fills_missing(tmp_path):
    _build_sources(tmp_path)
    (tmp_path / "record_index.json").write_text(json.dumps({
        "chats": ["m1", "m2", "m3", "ghost"], "docs": ["d1", "d2"],
        "tables": ["clientes:CL-1", "clientes:CL-2", "empleados:KP-1"]}))
    corpus = load_corpus(tmp_path)
    assert {r["id"] for r in corpus.chats} == {"m1", "m2", "m3", "ghost"}
    ghost = next(r for r in corpus.chats if r["id"] == "ghost")
    assert ghost["_placeholder"] and list(public_view(ghost)) == SCHEMA["chats"]
    assert {r["id"] for r in corpus.docs} == {"d1", "d2"}
    assert corpus.issues[0] == NO_ID_ISSUE
    assert corpus.issues[1].startswith("chats: 1 ids in record_index missing")
    assert corpus.issues[2].startswith("docs: 1 ids not in record_index dropped")
    assert len(corpus.issues) == 3


def _mock_api(files: dict[str, bytes], failures: dict[str, list]):
    """httpx transport emulating the sources API over an in-memory tree."""
    docs = {d["id"]: d["filename"] for d in json.loads(files["docs/index.json"])}

    def route(path: str) -> str | None:
        p = path.removeprefix("/v1/")
        fixed = {"chats/channels": "chats/channels.json", "chats/users": "chats/users.json",
                 "docs": "docs/index.json", "tables": "tables/index.json",
                 "record_index": "record_index.json", "tests/public": "tests_public.json"}
        if p in fixed:
            return fixed[p]
        parts = p.split("/")
        if parts[0] == "chats" and len(parts) == 3:
            return f"chats/{parts[1]}/{parts[2]}.json"
        if parts[0] == "docs" and len(parts) == 2:
            return f"docs/{docs.get(parts[1], '?')}"
        if parts[0] == "tables" and len(parts) == 2:
            return f"tables/{parts[1]}"
        return None

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        path = request.url.path
        queue = failures.get(path)
        if queue:
            kind = queue.pop(0)
            if kind == "timeout":
                raise httpx.ReadTimeout("slow", request=request)
            return httpx.Response(kind, headers={"Retry-After": "0"})
        parts = path.removeprefix("/v1/").split("/")
        if parts[0] == "chats" and len(parts) == 2 and parts[1] not in ("channels", "users"):
            days = sorted(k.split("/")[2][:-5] for k in files
                          if k.startswith(f"chats/{parts[1]}/"))
            return httpx.Response(200, json=days)
        rel = route(path)
        if rel is None or rel not in files:
            return httpx.Response(404, json={"error": "no existe"})
        return httpx.Response(200, content=files[rel])

    return httpx.Client(transport=httpx.MockTransport(handler),
                        headers={"Authorization": "Bearer secret"})


def test_fetch_all_offline_with_retries(tmp_path):
    files = _build_sources(tmp_path / "src")
    failures = {"/v1/chats/soporte/2026-08-01": [429, 503], "/v1/docs/d3": ["timeout"],
                "/v1/tables/clientes.csv": [500]}
    dest = tmp_path / "out" / "raw"
    with _mock_api(files, failures) as client:
        result = fetch_all("http://api.test/v1", "secret", dest, max_workers=4,
                           max_per_second=1000, client=client)
    assert result == dest
    got = {p.relative_to(dest).as_posix(): p.read_bytes()
           for p in dest.rglob("*") if p.is_file()}
    assert got == files
    assert not any(f for f in failures.values())  # every injected failure was consumed
    assert [p.name for p in dest.parent.iterdir()] == ["raw"]  # no staging left behind
    _assert_matches_index(load_corpus(dest), [NO_ID_ISSUE])

    # A second run replaces the managed tree and leaves foreign files alone.
    (dest / "notes.txt").write_text("keep me")
    (dest / "chats" / "stale.json").write_text("[]")
    with _mock_api(files, {}) as client:
        fetch_all("http://api.test", "secret", dest, max_per_second=1000, client=client)
    assert (dest / "notes.txt").read_text() == "keep me"  # base URL without /v1 also works
    assert not (dest / "chats" / "stale.json").exists()


def test_fetch_all_fails_clearly_and_leaves_dest_untouched(tmp_path):
    files = _build_sources(tmp_path / "src")
    del files["docs/carta.pdf"]  # the API now 404s on /docs/d3
    dest = tmp_path / "out" / "raw"
    with _mock_api(files, {}) as client, pytest.raises(FetchError, match="docs/carta.pdf"):
        fetch_all("http://api.test/v1", "secret", dest, max_per_second=1000, client=client)
    assert not dest.exists()
    assert list((tmp_path / "out").iterdir()) == []
