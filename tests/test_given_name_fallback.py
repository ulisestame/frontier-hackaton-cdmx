"""A bare given name that no context resolves: replaced when exactly one person carries it,
left as before when several do. Every name here is invented."""

from __future__ import annotations

from anon import fakes
from anon.core.engine import Ctx, Engine

SECRET = b"given-fallback-test"


def _engine() -> Engine:
    eng = Engine(fakes.PseudonymFactory(SECRET))
    eng.add_person("emp:1", "employee", "Leopoldo Iturbe Ledezma", city="Medellín")
    eng.add_person("cl:1", "customer", "Eustaquio Zubiría Villoria", city="Medellín")
    eng.add_person("emp:2", "employee", "Eustaquio Villoria Zubiría", city="Cali")
    eng.add_person("cl:2", "customer", "Julio Barragán Tobón", city="Cali")
    eng.f = fakes.PseudonymFactory(SECRET, {"leopoldo", "iturbe", "ledezma", "eustaquio", "zubiria", "villoria",
                                            "julio", "barragan", "tobon"})
    return eng


def _run(eng: Engine, text: str, rid: str = "doc") -> str:
    return eng.anonymize_text(text, Ctx(record_id=rid, record_text=text))


def test_single_carrier_without_context_is_replaced():
    eng = _engine()
    out = _run(eng, "Mañana Leopoldo revisa el informe de cierre.")
    assert "Leopoldo" not in out
    assert out.startswith("Mañana ") and out.endswith(" revisa el informe de cierre.")
    assert "doc" in eng.persons["emp:1"].records


def test_a_given_name_that_opens_an_unknown_full_name_is_not_given_to_the_carrier():
    eng = _engine()
    for rid, text in (("m0", "Leopoldo Ozámiz llamó ayer."), ("m1", "Ayer hablé con Leopoldo Ozámiz del caso.")):
        out = _run(eng, text, rid)
        assert "Leopoldo" not in out and "Ozámiz" not in out  # the whole unknown name is replaced
        assert rid not in eng.persons["emp:1"].records


def test_several_carriers_are_left_as_before_and_add_no_entity():
    eng = _engine()
    before = set(eng.persons)
    out = _run(eng, "Buenas tardes Eustaquio, te atiende el equipo.", "m1")
    assert "Eustaquio" in out
    assert set(eng.persons) == before
    assert "m1" not in eng.persons["cl:1"].records and "m1" not in eng.persons["emp:2"].records


def test_a_given_name_that_is_also_a_month_needs_a_cue():
    eng = _engine()
    assert _run(eng, "Julio cerró con buenas cifras.").startswith("Julio ")
    assert "Julio" not in _run(eng, "Lo atendió el señor Julio ayer.")


def test_resolved_mentions_are_unchanged():
    eng = _engine()
    text = "Eustaquio Villoria Zubiría atiende hoy. Gracias, Eustaquio."
    out = _run(eng, text, "m3")
    full = eng.render_name(eng.persons["emp:2"], 1, 2, "Eustaquio Villoria", text, 0, 18)
    assert out.split(".")[0].startswith(full.split()[0])  # the record names emp:2 in full
    assert "Eustaquio" not in out
