"""Documents: the identifier on a mention's own line decides between homonyms.

Every name and key here is invented.
"""

from __future__ import annotations

from anon import fakes
from anon.core.engine import Ctx, Engine
from anon.core.pipeline import SECRET, process_doc

NAME = "Renata Oquendo Lizcano"


def _engine() -> Engine:
    eng = Engine(fakes.PseudonymFactory(SECRET))
    for pid, key in (("cl:CL-90001", "CL-90001"), ("cl:CL-90002", "CL-90002")):
        eng.add_person(pid, "customer", NAME, city="Bogotá")  # true homonyms: same full name
        eng.index_id(pid, "key", key)
    eng.f = fakes.PseudonymFactory(SECRET, {"renata", "oquendo", "lizcano"})
    return eng


def _doc(body: str) -> dict:
    return {"id": "doc_t", "format": "md", "filename": "informe_prueba.md", "title": "Informe", "body": body,
            "metadata": {}}


def _full(eng: Engine, pid: str) -> str:
    return eng.pname(eng.persons[pid])["full"]


def test_each_line_goes_to_the_homonym_its_own_key_names():
    eng = _engine()
    body = f"| CL-90001 | {NAME} | abierta |\n| CL-90002 | {NAME} | cerrada |"
    lines = process_doc(eng, _doc(body))["body"].splitlines()
    assert _full(eng, "cl:CL-90001") in lines[0] and _full(eng, "cl:CL-90002") in lines[1]
    assert not [w for w in eng.warnings if w.startswith("ambiguous")]


def test_a_line_without_a_key_falls_back_to_the_document():
    eng = _engine()
    body = f"Radicado de CL-90002.\n\n{NAME} pidió revisión del cobro."
    out = process_doc(eng, _doc(body))["body"]
    assert _full(eng, "cl:CL-90002") in out.splitlines()[-1]


def test_chats_do_not_read_lines():
    eng = _engine()
    text = f"CL-90001 y CL-90002\n{NAME} escribió"
    eng.anonymize_text(text, Ctx(record_id="m1", record_text=text))  # no line rule outside documents
    assert [w for w in eng.warnings if w.startswith("ambiguous")]
