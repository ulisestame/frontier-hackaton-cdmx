"""Self-check repair: a declared original still in the output is replaced, then checked again.

Invented values only (names, cédulas and e-mails are not from the corpus or the sample).
"""

from __future__ import annotations

import copy

from anon import fakes
from anon.core.engine import Engine
from anon.core.pipeline import Haystack
from anon.core.selfcheck import locate, mapped_compact, mapped_norm, repair_leaks
from anon.core.textnorm import compact_digits, contains, norm

SECRET = b"selfcheck-repair-test"
CEDULA = "1093418276"
EMAIL = "lorena.cifuentes@example.com"


def _engine() -> Engine:
    eng = Engine(fakes.PseudonymFactory(SECRET))
    eng.add_person("cl:1", "customer", "Lorena Cifuentes Bedoya", city="Bogotá")
    eng.index_id("cl:1", "cedula", CEDULA)
    eng.index_id("cl:1", "email", EMAIL)
    eng.add_person("cl:2", "customer", "Tomás Felipe Corredor Ibarra", city="Cali")
    eng.f = fakes.PseudonymFactory(SECRET, {"lorena", "cifuentes", "bedoya", "tomas", "felipe", "corredor", "ibarra"})
    return eng


def _chat(rid: str, text: str, author: str, filename: str | None = None) -> dict:
    return {"id": rid, "thread_id": "soporte:1.000100", "author": author, "ts": "1.000100", "text": text,
            "attachments": [{"filename": filename}] if filename else []}


def _declared(eng: Engine, pid: str, rid: str, originals: list[str]) -> str:
    """Mark `pid` as published in `rid` (its pseudonym is there) with these declared originals."""
    p = eng.persons[pid]
    short = eng.pname(p)["short"]
    eng.note(p, rid, "", "name", short)
    for o in originals:
        p.originals.add(o)
    return short


def _only_change(before: dict, after: dict, field: tuple, old: str, new: str) -> None:
    """`after` equals `before` except that `old` became `new` inside one field."""
    expected = copy.deepcopy(before)
    target = expected
    for step in field[:-1]:
        target = target[step]
    assert old in target[field[-1]]
    target[field[-1]] = target[field[-1]].replace(old, new)
    assert after == expected


def test_mapping_reproduces_the_validator_normalization():
    for raw in ("Lorena  Cifuentes​ Bédoya", "LORENA CIFUENTES", "Straße ﬁn", "Ｌｏｒｅｎａ cаfé",
                "CC 1.093.418.276 / 109-341-8276", "tel +57 315 604 2817", ""):
        mapped = mapped_norm(raw)
        assert mapped is not None and mapped[0] == norm(raw)
        compact = mapped_compact(raw)
        assert compact is not None and compact[0] == compact_digits(raw)


def test_locate_finds_what_contains_finds_in_raw_characters():
    text = "Hola LORENA CIFUENTES, tu CC 1.093.418.276 y lorena​cifuentes"
    for needle in ("Lorena Cifuentes", CEDULA):
        spans = locate(text, needle)
        assert spans and contains(text, needle)
        for s, e in spans:
            assert contains(text[s:e], needle)


def test_attachment_slug_is_repaired_as_a_slug():
    eng = _engine()
    short = _declared(eng, "cl:1", "m0", ["lorena_cifuentes"])
    published = _chat("m0", f"Hola {short}", "Kipi")
    leaked = _chat("m1", "Adjunto el extracto.", short, filename="extracto_lorena_cifuentes_julio.pdf")
    before = copy.deepcopy(leaked)
    repaired, hay = repair_leaks(eng, [published, leaked], Haystack)
    slug = eng.render_name(eng.persons["cl:1"], 1, 1, "lorena_cifuentes", "", 0, 0)
    assert repaired == {"name": 1}
    assert "_" in slug and " " not in slug
    _only_change(before, leaked, ("attachments", 0, "filename"), "lorena_cifuentes", slug)
    assert not hay.has("lorena_cifuentes")


def test_dotted_cedula_inside_text_keeps_its_grouping():
    eng = _engine()
    short = _declared(eng, "cl:1", "m1", [CEDULA])
    leaked = _chat("m1", f"Mi cédula es 1.093.418.276, gracias. Atentamente {short}", short)
    before = copy.deepcopy(leaked)
    repaired, hay = repair_leaks(eng, [leaked], Haystack)
    pseudo = fakes.format_like("1.093.418.276", eng.pseudo("cedula", eng.persons["cl:1"], CEDULA))
    assert repaired == {"cedula": 1}
    assert pseudo != "1.093.418.276" and pseudo.count(".") == 3
    _only_change(before, leaked, ("text",), "1.093.418.276", pseudo)
    assert not hay.has(CEDULA)


def test_email_in_doc_metadata_is_repaired():
    eng = _engine()
    short = _declared(eng, "cl:1", "doc_1", [EMAIL])
    doc = {"id": "doc_1", "format": "md", "filename": "acta.md", "title": "Acta de cierre",
           "body": f"Preparado por {short}.", "metadata": {"author": EMAIL, "subject": "cierre"}}
    before = copy.deepcopy(doc)
    repaired, hay = repair_leaks(eng, [doc], Haystack)
    pseudo = eng.pseudo("email", eng.persons["cl:1"], EMAIL)
    assert repaired == {"email": 1} and "@" in pseudo and pseudo != EMAIL
    _only_change(before, doc, ("metadata", "author"), EMAIL, pseudo)
    assert not hay.has(EMAIL)


def test_overlap_with_another_persons_pseudonym_is_skipped():
    eng = _engine()
    _declared(eng, "cl:1", "m0", ["Ana Milena"])
    other = eng.persons["cl:2"]
    eng.note(other, "m1", "", "name", "Ana Milena Pardo")  # cl:2's pseudonym contains the original
    published = _chat("m0", f"Hola {eng.pname(eng.persons['cl:1'])['short']}", "Kipi")
    record = _chat("m1", "Te atiende Ana Milena Pardo.", "Kipi")
    before = copy.deepcopy(record)
    repaired, hay = repair_leaks(eng, [published, record], Haystack)
    assert repaired == {}
    assert record == before  # left to the last resort: undeclared and reported
    assert hay.has("Ana Milena")


def test_nothing_to_repair_changes_nothing():
    eng = _engine()
    short = _declared(eng, "cl:1", "m0", [CEDULA, EMAIL, "Lorena Cifuentes"])
    records = [_chat("m0", f"Hola {short}, tu caso quedó registrado.", short)]
    before = copy.deepcopy(records)
    repaired, _ = repair_leaks(eng, records, Haystack)
    assert repaired == {} and records == before
