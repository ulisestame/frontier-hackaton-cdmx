"""A person whose name or surname equals a kept term (brand, place, public figure): the role
in context decides, not the name. Every name, term and value here is invented."""

from __future__ import annotations

import pytest

from anon import fakes
from anon.core import engine as E
from anon.core.engine import Ctx, Engine
from anon.core.pipeline import process_table_row, register_table_row, render_chat

SECRET = b"kept-role-test"
FIGURE = "Celestino Arbeláez"  # an invented public figure
PLACE = "Pradomar"  # an invented place


@pytest.fixture()
def eng(monkeypatch):
    monkeypatch.setattr(E, "KEPT_TERMS", E.KEPT_TERMS + [FIGURE, PLACE])
    monkeypatch.setattr(E, "_KEPT_NORM", E._KEPT_NORM | {E.norm(FIGURE), E.norm(PLACE)})
    eng = Engine(fakes.PseudonymFactory(SECRET))
    for key, name, doc, mail, phone in (("CL-90950", FIGURE, "71900001", "carbelaez@example.com", "3009990001"),
                                        ("CL-90951", "Rosa Pradomar Vélez", "71900002", "rpradomar@example.com",
                                         "3009990002")):
        register_table_row(eng, {"id": f"clientes:{key}", "table": "clientes", "columns": {
            "cliente_id": key, "nombre_completo": name, "tipo_doc": "CC", "num_doc": doc, "correo": mail,
            "celular": phone, "ciudad": "Cali", "barrio": "", "direccion": "", "fecha_nacimiento": "1981-03-09",
            "fecha_vinculacion": "2024-02-01", "ocupacion": "",
            "notas": f"{name} pide que lo llamen después de las 5."}})
    eng.f = fakes.PseudonymFactory(SECRET, {fakes.normalize_token(t) for p in eng.persons.values()
                                            for w in p.given + p.surnames for t in w.split()})
    return eng


def _chat(eng, pid, text):
    m = {"id": "m1", "thread_id": "soporte:1", "author": eng.persons[pid].full, "ts": "1", "text": text,
         "attachments": [], "_user": "U1", "_is_bot": False}
    return render_chat(eng, m, pid, {pid}, pid)


def test_author_field_is_replaced(eng):
    out = _chat(eng, "cl:CL-90950", "Buenas tardes.")
    assert out["author"] == eng.pname(eng.persons["cl:CL-90950"])["short"] != FIGURE


def test_self_introduction_is_replaced(eng):
    out = _chat(eng, "cl:CL-90950", f"Hola, soy {FIGURE} y no reconozco un cobro.")
    assert FIGURE not in out["text"]


def test_own_table_row_is_replaced(eng):
    row = next(r for r in [{"id": "clientes:CL-90950", "table": "clientes",
                            "columns": {"cliente_id": "CL-90950", "nombre_completo": FIGURE, "tipo_doc": "CC",
                                        "num_doc": "71900001", "correo": "carbelaez@example.com",
                                        "celular": "3009990001", "ciudad": "Cali", "barrio": "", "direccion": "",
                                        "fecha_nacimiento": "1981-03-09", "fecha_vinculacion": "2024-02-01",
                                        "ocupacion": "", "notas": f"{FIGURE} pide que lo llamen después de las 5."}}])
    cols = process_table_row(eng, row)["columns"]
    assert FIGURE not in cols["nombre_completo"]
    assert FIGURE not in cols["notas"]


def test_surname_that_is_a_place_names_the_person(eng):
    out = _chat(eng, "cl:CL-90951", "Soy Rosa Pradomar, me cobraron dos veces.")
    assert "Rosa Pradomar" not in out["text"]


def test_plain_reference_elsewhere_stays_kept(eng):
    text = f"Anoche vi a {FIGURE} en televisión hablando de {PLACE}."
    out = eng.anonymize_text(text, Ctx(record_id="doc_k", record_text=text))
    assert out == text


def test_name_starting_with_a_kept_term_is_replaced_where_it_names_the_person(monkeypatch):
    monkeypatch.setattr(E, "KEPT_TERMS", E.KEPT_TERMS + [FIGURE])
    monkeypatch.setattr(E, "_KEPT_NORM", E._KEPT_NORM | {E.norm(FIGURE)})
    eng = Engine(fakes.PseudonymFactory(SECRET))
    register_table_row(eng, {"id": "clientes:CL-90952", "table": "clientes", "columns": {
        "cliente_id": "CL-90952", "nombre_completo": f"{FIGURE} Mora", "tipo_doc": "CC", "num_doc": "71900003",
        "correo": "cmora@example.com", "celular": "3009990003", "ciudad": "Cali", "barrio": "", "direccion": "",
        "fecha_nacimiento": "1981-03-09", "fecha_vinculacion": "2024-02-01", "ocupacion": "", "notas": ""}})
    eng.f = fakes.PseudonymFactory(SECRET, {"celestino", "arbelaez", "mora"})
    own = _chat(eng, "cl:CL-90952", f"Soy {FIGURE}, escribo de nuevo por el cobro.")
    assert FIGURE not in own["text"]  # the short form names the anchored person
    text = f"Anoche vi a {FIGURE} en televisión."
    assert eng.anonymize_text(text, Ctx(record_id="doc_k2", record_text=text)) == text
