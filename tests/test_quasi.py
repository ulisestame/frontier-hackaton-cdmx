"""Occupation, barrio and joining year are generalized together, whatever the phrasing.

The barrio is invented and registered for the test only.
"""

from __future__ import annotations

import pytest

from anon import fakes
from anon.core.engine import Engine, Person

BARRIO = "Villa Inventada"


@pytest.fixture()
def eng():
    saved = (dict(fakes.CITY_OF_BARRIO), {k: list(v) for k, v in fakes.CITIES_OF_BARRIO.items()},
             {k: list(v) for k, v in fakes.BARRIOS_BY_CITY.items()},
             {k: list(v) for k, v in fakes.CORPUS_BARRIOS_BY_CITY.items()})
    fakes.register_barrio("Cali", BARRIO)
    yield Engine(fakes.PseudonymFactory(b"quasi-test"))
    for live, old in zip((fakes.CITY_OF_BARRIO, fakes.CITIES_OF_BARRIO, fakes.BARRIOS_BY_CITY,
                          fakes.CORPUS_BARRIOS_BY_CITY), saved):
        live.clear()
        live.update(old)


def test_third_person_occupation_and_barrio_are_generalized(eng):
    out = eng.generalize_quasi(f"El afectado es arquitecto, vive en {BARRIO} y es cliente desde 2020.")
    assert "arquitecto" not in out and BARRIO not in out and "2020" not in out
    assert "Cali" in out and "profesional de la construcción" in out


def test_second_person_without_a_cue(eng):
    out = eng.generalize_quasi(f"En la solicitud pusiste que trabajas como veterinaria y que vives en {BARRIO}.")
    assert "veterinaria" not in out and BARRIO not in out


def test_one_component_that_matches_the_customer_master_row(eng):
    me = Person(pid="cl:1", kind="customer", given=["Ana"], surnames=["Pérez"], city="Cali",
                occupation="fotógrafa", barrio=BARRIO)
    out = eng.generalize_quasi(f"Mi dirección es Calle 1 # 2-3, {BARRIO}, Cali.", me.city, me)
    assert BARRIO not in out


def test_english_phrasing(eng):
    out = eng.generalize_quasi(f"The customer is an accountant from {BARRIO} since 2019.")
    assert "accountant" not in out and BARRIO not in out and "2019" not in out
    assert "finance professional" in out


def test_a_place_alone_stays(eng):
    for text in (f"La reunión de equipo fue en {BARRIO}.", f"Abrimos oficina en {BARRIO} en 2026."):
        assert eng.generalize_quasi(text) == text
