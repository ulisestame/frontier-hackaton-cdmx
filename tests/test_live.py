"""Live /anonymize must reproduce what the full run published, record for record.

Uses the small sample corpus (data/ is gitignored; the tests skip without it).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from anon.core import pipeline as P
from anon.parse import load_corpus, public_view

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "input"
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample corpus not present")


@pytest.fixture()
def published(tmp_path):
    corpus = load_corpus(SAMPLE)
    eng, ids, chats, docs, tables, _, _ = P.anonymize_corpus(corpus, tmp_path)
    P.save_state(tmp_path, eng, ids)
    P._LIVE_CACHE.clear()
    return corpus, tmp_path, {r["id"]: r for r in chats + docs + tables}


@pytest.mark.parametrize("source", ["chats", "docs", "tables"])
def test_live_reproduces_the_batch_output(published, source):
    corpus, state, batch = published
    records = [public_view(r) for r in getattr(corpus, source)]
    got = P.anonymize_live(source, records, state)["records"]
    assert got == [batch[r["id"]] for r in records]


def test_record_keys_survive_in_the_state(published):
    corpus, state, _ = published
    eng = P.engine_from_state(P.load_state(state))
    keys = [r["columns"]["cliente_id"] for r in corpus.tables if r["table"] == "clientes"]
    assert keys and all(eng.id_index.get(("key", k)) for k in keys)
    assert eng.threads and eng.authors


def test_new_homonyms_get_two_pseudonyms_and_their_data_replaced(published):
    corpus, state, _ = published
    base = next(r for r in corpus.tables if r["table"] == "clientes")
    rows = []
    for i, (doc, mail) in enumerate((("1093456781", "nuevo.cliente@gmail.com"), ("52789012", "otro@hotmail.com"))):
        cols = dict(base["columns"], cliente_id=f"CL-9900{i}", nombre_completo="Rosalinda Quiñones Tafur",
                    num_doc=doc, correo=mail, celular=f"31{i}5551234")
        rows.append({"id": f"clientes:CL-9900{i}", "table": "clientes", "columns": cols})
    out = P.anonymize_live("tables", rows, state)["records"]
    names = [o["columns"]["nombre_completo"] for o in out]
    assert len(set(names)) == 2 and "Rosalinda Quiñones Tafur" not in names
    for o, r in zip(out, rows):
        for col in ("num_doc", "correo", "celular", "barrio", "ocupacion"):
            assert o["columns"][col] != r["columns"][col], col


def test_live_cache_is_per_state_file(published, tmp_path_factory):
    corpus, state, batch = published
    other = tmp_path_factory.mktemp("other-state")
    rec = public_view(corpus.chats[1])
    P.anonymize_live("chats", [rec], state)
    empty = P.anonymize_live("chats", [rec], other)["records"][0]  # no state there: not the cached engine
    assert P._LIVE_CACHE["mtime"][0] == str(other / P.STATE_FILE)
    assert P.anonymize_live("chats", [rec], state)["records"][0] == batch[rec["id"]]
    assert empty["id"] == rec["id"]


def test_a_new_author_owns_the_identifiers_in_their_message(published):
    _, state, _ = published
    msg = {"id": "live-1", "thread_id": "soporte-cobros:9999999999.000100", "author": "Rosalinda Quiñones Tafur",
           "ts": "9999999999.000100", "attachments": [],
           "text": "Hola, mi cédula es 1093456781 y mi correo es rquinones@gmail.com"}
    res = P.anonymize_live("chats", [msg], state)
    text = res["records"][0]["text"]
    assert "1093456781" not in text and "rquinones@gmail.com" not in text
    ent = next(e for e in res["entities"] if "Rosalinda Quiñones Tafur" in e["originals"])
    assert {"name", "cedula", "email"} <= set(ent["pseudonyms"])


def _as_previous_version(state: Path, dest: Path) -> Path:
    """The state a run of the previous version wrote: no chat context, no persisted keys."""
    data = P.load_state(state)
    data.pop("threads", None)
    data.pop("authors", None)
    for p in data["persons"].values():
        p["ids"].pop("key", None)
    (dest / P.STATE_FILE).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return dest


def test_a_new_run_on_a_previous_version_state_keeps_every_pseudonym(tmp_path_factory):
    first = tmp_path_factory.mktemp("run1")
    eng, ids, *_, ents1, _ = P.anonymize_corpus(load_corpus(SAMPLE), first)
    P.save_state(first, eng, ids)
    old = _as_previous_version(first, tmp_path_factory.mktemp("run1-old-format"))
    *_, ents2, _ = P.anonymize_corpus(load_corpus(SAMPLE), old)
    pseud = lambda ents: {e["entity_id"]: e["pseudonyms"] for e in ents if not e.get("kept")}  # noqa: E731
    assert pseud(ents2) == pseud(ents1)


def test_live_on_a_previous_version_state(published, tmp_path_factory):
    corpus, state, batch = published
    old = _as_previous_version(state, tmp_path_factory.mktemp("run1-state"))
    P._LIVE_CACHE.clear()
    rows = [public_view(r) for r in corpus.tables]
    assert P.anonymize_live("tables", rows, old)["records"] == [batch[r["id"]] for r in rows]
    chats = [public_view(r) for r in corpus.chats]
    assert [g["id"] for g in P.anonymize_live("chats", chats, old)["records"]] == [c["id"] for c in chats]
