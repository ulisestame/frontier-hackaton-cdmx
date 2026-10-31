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


# ----------------------------------------------------------------- "reporta a" ---

def _employee(key: str, name: str, boss: str, mail: str, phone: str, doc: str) -> dict:
    return {"id": f"empleados:{key}", "table": "empleados", "columns": {
        "id": key, "cargo": "Analista de Operaciones", "ciudad": "Cali", "ingreso": "2022", "reporta_a": boss,
        "nombre": name, "correo": mail, "celular": phone, "documento": doc, "documento_tipo": "CC",
        "fecha_nacimiento": "1988-02-14"}}


def _customer(key: str, name: str, mail: str, phone: str, doc: str) -> dict:
    return {"id": f"clientes:{key}", "table": "clientes", "columns": {
        "cliente_id": key, "nombre_completo": name, "tipo_doc": "CC", "num_doc": doc, "correo": mail,
        "celular": phone, "ciudad": "Cali", "barrio": "", "direccion": "", "fecha_nacimiento": "1979-07-30",
        "fecha_vinculacion": "2024-01-15", "ocupacion": "", "notas": ""}}


def _company() -> tuple[Engine, dict]:
    from anon.core.pipeline import register_table_row
    rows = {
        "cust": _customer("CL-90901", "Ramiro Quintana Pardo", "rquintana@example.com", "3001110001", "71000001"),
        "boss": _employee("KP-901", "Ramiro Quintana Velasco", "", "ramiro.quintana@example.co", "3001110002",
                          "71000002"),
        "report": _employee("KP-902", "Celina Aranda Mora", "Ramiro Quintana", "celina.aranda@example.co",
                            "3001110003", "71000003"),
    }
    eng = Engine(fakes.PseudonymFactory(SECRET))
    for r in rows.values():
        register_table_row(eng, r)
    eng.f = fakes.PseudonymFactory(SECRET, _blocked(eng))
    return eng, rows


def test_reporta_a_goes_to_the_employee_not_to_a_customer_with_the_same_short_name():
    from anon.core.pipeline import process_table_row
    eng, rows = _company()
    out = process_table_row(eng, rows["report"])["columns"]["reporta_a"]
    boss, cust = eng.pname(eng.persons["kp:KP-901"]), eng.pname(eng.persons["cl:CL-90901"])
    assert out == boss["short"] != cust["short"]
    assert "empleados:KP-902" in eng.persons["kp:KP-901"].records
    assert "empleados:KP-902" not in eng.persons["cl:CL-90901"].records


def test_reporta_a_without_a_known_boss_is_still_anonymized():
    from anon.core.pipeline import process_table_row
    eng, rows = _company()
    row = _employee("KP-903", "Celina Aranda Mora", "Hernando Aguilar", "otra@example.co", "3001110004", "71000004")
    out = process_table_row(eng, row)["columns"]["reporta_a"]
    assert "Hernando" not in out and "Aguilar" not in out
