"""Regression: an initial plus a surname ("L. Cifuentes") is a name form (invented values)."""

from __future__ import annotations

from anon import fakes
from anon.core.engine import Ctx, Engine

SECRET = b"initial-surname-test"


def _engine() -> Engine:
    eng = Engine(fakes.PseudonymFactory(SECRET))
    eng.add_person("cl:1", "customer", "Lorena Cifuentes Bedoya", city="Bogotá")
    eng.add_person("cl:2", "customer", "Mateo Ruiz Gómez", city="Medellín")
    eng.add_person("cl:3", "customer", "Marta Ruiz Pardo", city="Cali")
    eng.f = fakes.PseudonymFactory(SECRET, {"lorena", "cifuentes", "bedoya", "mateo", "ruiz", "gomez",
                                            "marta", "pardo"})
    return eng


def _run(eng, text, rid="t1"):
    return eng.anonymize_text(text, Ctx(record_id=rid, record_text=text))


def test_unique_initial_and_surname_gets_the_pseudonym_initial_and_surname():
    eng = _engine()
    out = _run(eng, "Transferencia a cuenta propia - L. Cifuentes")
    pn = eng.pname(eng.persons["cl:1"])
    assert out == f"Transferencia a cuenta propia - {pn['given'][0][0]}. {pn['surnames'][0]}"
    assert "cl:1" in {eng.resolve_pid(pid) for pid in [eng.persons["cl:1"].pid]}
    assert "t1" in eng.persons["cl:1"].records


def test_second_surname_is_replaced_too():
    eng = _engine()
    out = _run(eng, "Firmado: L. Cifuentes Bedoya.")
    pn = eng.pname(eng.persons["cl:1"])
    assert out == f"Firmado: {pn['given'][0][0]}. {pn['surnames'][0]} {pn['surnames'][1]}."


def test_shared_or_unknown_initial_surname_is_left_and_listed():
    eng = _engine()
    text = "Pagos de M. Ruiz y de T. Cifuentes."
    assert _run(eng, text, "t2") == text
    assert ("t2", "M. Ruiz", 2) in eng.initials_left
    assert ("t2", "T. Cifuentes", 0) in eng.initials_left
