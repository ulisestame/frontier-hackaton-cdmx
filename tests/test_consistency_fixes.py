"""Regression tests for cross-source consistency: kept terms that open a longer span,
ties between people of different kinds, and the "reporta a" relation between employees.

Every name, id and value here is invented.
"""

from __future__ import annotations

from anon import fakes
from anon.core.engine import Ctx, Engine

SECRET = b"consistency-fixes-test"


def _blocked(eng: Engine) -> set[str]:
    return {fakes.normalize_token(t) for p in eng.persons.values() for w in p.given + p.surnames for t in w.split()}


# ----------------------------------------------------- kept terms opening a longer span ---

def test_a_brand_followed_by_a_place_is_not_a_person():
    eng = Engine(fakes.PseudonymFactory(SECRET))
    first = eng.anonymize_text("Compra Juan Valdez Laureles", Ctx(record_id="tx:1"))
    later = eng.anonymize_text("Compra Juan Valdez", Ctx(record_id="tx:2"))
    assert first == "Compra Juan Valdez Laureles"
    assert later == "Compra Juan Valdez"
    assert not [pid for pid in eng.persons if pid.startswith("x:name:")]
    assert "Juan Valdez" in eng.kept_seen


def test_an_exact_kept_mention_is_kept_even_if_a_longer_name_shares_it():
    eng = Engine(fakes.PseudonymFactory(SECRET))
    eng.add_person("x:name:juan valdez quintero", "external", "Juan Valdez Quintero")
    out = eng.anonymize_text("Nos vemos en Juan Valdez a las tres.", Ctx(record_id="chat:1"))
    assert out == "Nos vemos en Juan Valdez a las tres."


def test_an_unknown_full_name_is_still_replaced():
    eng = Engine(fakes.PseudonymFactory(SECRET))
    out = eng.anonymize_text("Me atendió Rosaura Benítez Quiroga ayer.", Ctx(record_id="chat:2"))
    assert "Rosaura" not in out and "Benítez" not in out
