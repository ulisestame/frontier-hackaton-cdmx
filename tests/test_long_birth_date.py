"""A birth date written out in Spanish words is replaced like the ISO and slash forms.

Every name and date here is invented.
"""

from __future__ import annotations

import re

from anon import fakes
from anon.core.engine import Ctx, Engine
from anon.core.pipeline import SECRET


def _engine() -> Engine:
    eng = Engine(fakes.PseudonymFactory(SECRET))
    eng.add_person("cl:CL-90001", "customer", "Renata Oquendo Lizcano", city="Bogotá")
    eng.index_id("cl:CL-90001", "birth", "1991-04-07")
    return eng


def _run(text: str) -> str:
    return _engine().anonymize_text(text, Ctx(record_id="m1", record_text=text))


def test_a_registered_birth_date_in_words_is_replaced_in_the_same_form():
    out = _run("Para validar: nací el 7 de abril de 1991.")
    assert "7 de abril de 1991" not in out
    assert re.search(r"nací el \d{1,2} de [a-z]+ de \d{4}\.$", out)


def test_abbreviated_month_and_no_de():
    out = _run("Fecha de nacimiento: 07 Abr 1991")
    assert "07 Abr 1991" not in out
    assert re.search(r"nacimiento: \d{2} [A-Z][a-z]{2} \d{4}$", out)


def test_a_date_that_is_nobody_s_birth_date_is_left():
    assert _run("El pago del 7 de abril de 2026 quedó aplicado.") == "El pago del 7 de abril de 2026 quedó aplicado."
