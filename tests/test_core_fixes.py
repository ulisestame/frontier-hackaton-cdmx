"""Regression tests for the core fixes: occupation generalization, slash dates in both
orders, barrios that exist in several cities, and reservation of real values."""

from __future__ import annotations

import re

from anon import fakes
from anon.core.engine import Ctx, Engine
from anon.core.pipeline import _reserve_real_values

SECRET = b"core-fixes-test"


def _engine() -> Engine:
    eng = Engine(fakes.PseudonymFactory(SECRET))
    eng.add_person("cl:1", "customer", "Lorena Cifuentes Bedoya", city="Bogotá")
    eng.index_id("cl:1", "birth", "1991-04-09")
    eng.add_person("cl:2", "customer", "Mateo Ruiz Gómez", city="Medellín")
    eng.index_id("cl:2", "birth", "1985-11-23")
    eng.index_id("cl:2", "cedula", "70482916")
    eng.f = fakes.PseudonymFactory(SECRET, {"lorena", "cifuentes", "bedoya", "mateo", "ruiz", "gomez"})
    _reserve_real_values(eng)
    return eng


def test_occupation_is_generalized_once():
    eng = _engine()
    out = eng.generalize_quasi("Yo soy estudiante de derecho, vivo en Laureles y entré en 2023.")
    assert out == "Yo soy estudiante de educación superior, vivo en Medellín y entré en hace unos años."


def test_text_without_an_occupation_cue_is_untouched():
    eng = _engine()
    text = "El piloto del programa arrancó y el cajero automático no entrega billetes."
    assert eng.generalize_quasi(text) == text


def test_ambiguous_barrio_uses_the_record_city():
    eng = _engine()
    text = "Soy contadora, vivo en Castilla desde 2021."
    assert "Bogotá" in eng.generalize_quasi(text, "Bogotá")
    assert "Medellín" in eng.generalize_quasi(text, "Medellín")
    # no city known (or a city without that barrio): the default mapping
    default = fakes.CITY_OF_BARRIO[fakes.normalize_token("Castilla")]
    assert default in eng.generalize_quasi(text) and default in eng.generalize_quasi(text, "Cali")


def test_month_first_slash_date_is_found_and_keeps_its_layout():
    eng = _engine()
    iso = eng.pseudo("birth", eng.persons["cl:1"], "1991-04-09")
    out = eng.anonymize_text("Lorena Cifuentes Bedoya, DOB 04/09/1991", Ctx(record_id="r1"))
    m = re.search(r"DOB (\d{2})/(\d{2})/(\d{4})", out)
    assert m and "04/09/1991" not in out
    assert f"{m[3]}-{m[1]}-{m[2]}" == iso  # month first, same shifted date as the ISO pseudonym


def test_day_first_slash_date_still_works():
    eng = _engine()
    iso = eng.pseudo("birth", eng.persons["cl:2"], "1985-11-23")
    out = eng.anonymize_text("Nació el 23/11/1985 en Medellín.", Ctx(record_id="r2", owner="cl:2"))
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", out)
    assert m and f"{m[3]}-{m[2]}-{m[1]}" == iso


def test_real_values_are_reserved_before_generation():
    eng = _engine()
    assert "1991-04-09" in eng.f.reserved["birth"]
    assert "70482916" in eng.f.reserved["cedula"]
