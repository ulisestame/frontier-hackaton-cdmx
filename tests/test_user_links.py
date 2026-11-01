"""Linking chat users to the registry when a name matches more than one person.

Every name, number and address here is invented.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from anon import fakes
from anon.core.engine import Engine
from anon.core.pipeline import SECRET, build_registry

LIZCANO = {"cliente_id": "CL-90001", "nombre_completo": "Renata Oquendo Lizcano", "num_doc": "1012345678",
           "correo": "renata.lizcano@example.com", "celular": "3001112233", "direccion": "Calle 12B # 34-56 apto 301",
           "fecha_nacimiento": "1991-04-07", "ciudad": "Bogotá"}
VELEZ = {"cliente_id": "CL-90002", "nombre_completo": "Renata Oquendo Vélez", "num_doc": "52987654",
         "correo": "roquendo@example.com", "celular": "3104441998", "direccion": "Carrera 80 # 9-12",
         "fecha_nacimiento": "1984-11-23", "ciudad": "Medellín"}
STAFF = {"id": "KP-901", "nombre": "Renata Oquendo Lizcano", "correo": "renata.oquendo@kipupay.co",
         "celular": "3157778899", "documento": "1098765432", "fecha_nacimiento": "1990-01-15", "ciudad": "Bogotá"}


def _registry(users: dict, chats: list[dict], staff: bool = False) -> Engine:
    tables = [{"id": f"clientes:{c['cliente_id']}", "table": "clientes", "columns": c} for c in (LIZCANO, VELEZ)]
    if staff:
        tables.append({"id": f"empleados:{STAFF['id']}", "table": "empleados", "columns": STAFF})
    eng = Engine(fakes.PseudonymFactory(SECRET))
    build_registry(eng, SimpleNamespace(tables=tables, users=users, chats=chats))
    return eng


def _user(name: str, title: str = "Cliente", email: str = "") -> dict:
    return {"real_name": name, "name": name.split()[0].lower(), "profile": {"title": title, "email": email}}


def _thread(uid: str, *texts: str, attachments: tuple[str, ...] = ()) -> list[dict]:
    msgs = [{"id": f"{uid}-{i}", "thread_id": f"t-{uid}", "_user": uid, "_is_bot": False, "text": t,
             "attachments": []} for i, t in enumerate(texts)]
    msgs[-1]["attachments"] = [{"filename": f} for f in attachments]
    return msgs


def test_a_customer_profile_is_not_linked_to_an_employee_homonym():
    eng = _registry({"U1": _user("Renata Oquendo Lizcano")}, _thread("U1", "hola"), staff=True)
    assert eng.resolve_pid("u:U1") == "cl:CL-90001"


def test_a_company_email_is_not_linked_to_a_customer_homonym():
    users = {"U1": _user("Renata Oquendo Lizcano", title="Analista", email="r.oquendo@kipupay.co")}
    eng = _registry(users, _thread("U1", "hola"), staff=True)
    assert eng.resolve_pid("u:U1") == "kp:KP-901"


@pytest.mark.parametrize("text, expected", [
    ("Los últimos 4 de la cédula: 5678", "cl:CL-90001"),
    ("nací el 23 de noviembre de 1984", "cl:CL-90002"),
    ("me la mandan a la cra 80 #9-12 por favor", "cl:CL-90002"),
    ("mi correo es renata punto lizcano arroba example punto com", "cl:CL-90001"),
])
def test_a_clue_in_the_thread_decides_between_homonyms(text, expected):
    eng = _registry({"U1": _user("Renata Oquendo")}, _thread("U1", "hola", text))
    assert eng.resolve_pid("u:U1") == expected


def test_a_full_name_in_an_attachment_decides_between_homonyms():
    chats = _thread("U1", "adjunto el soporte", attachments=("extracto_renata_oquendo_velez.pdf",))
    eng = _registry({"U1": _user("Renata Oquendo")}, chats)
    assert eng.resolve_pid("u:U1") == "cl:CL-90002"


@pytest.mark.parametrize("text", ["tengo la cuenta desde 1998", "la abrí el 3 de mayo de 1998"])
def test_a_year_is_not_read_as_the_last_digits(text):
    eng = _registry({"U1": _user("Renata Oquendo")}, _thread("U1", text))
    assert eng.resolve_pid("u:U1") == "u:U1"  # no clue: stays its own person


def test_a_homonym_linked_to_another_user_is_ruled_out():
    users = {"U1": _user("Renata Oquendo", email="roquendo@example.com"), "U2": _user("Renata Oquendo")}
    eng = _registry(users, _thread("U1", "hola") + _thread("U2", "buenas"))
    assert eng.resolve_pid("u:U1") == "cl:CL-90002"
    assert eng.resolve_pid("u:U2") == "cl:CL-90001"


def test_two_users_left_with_the_same_homonym_stay_unlinked():
    users = {"U1": _user("Renata Oquendo", email="roquendo@example.com"),
             "U2": _user("Renata Oquendo"), "U3": _user("Renata Oquendo")}
    eng = _registry(users, _thread("U1", "hola") + _thread("U2", "buenas") + _thread("U3", "hola"))
    assert eng.resolve_pid("u:U2") == "u:U2"  # both left with the same homonym: neither is decided
    assert eng.resolve_pid("u:U3") == "u:U3"


def test_the_new_clues_are_read_for_linking_only():
    eng = _registry({}, [])
    text = "La tarjeta va a la cra 80 #9-12; nació el 23 de noviembre de 1984."
    assert eng.evidence(text) == set()  # record processing does not read them
    assert eng.evidence_among(text, {"cl:CL-90001", "cl:CL-90002"}) == {"cl:CL-90002"}


SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "input"


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample corpus not present")
def test_a_user_split_in_an_earlier_run_folds_into_the_customer_who_keeps_its_pseudonym(tmp_path):
    from anon.core import pipeline as P
    from anon.parse import load_corpus

    def corpus(*texts: str):
        c = load_corpus(SAMPLE)
        for row in (LIZCANO, dict(VELEZ, nombre_completo=LIZCANO["nombre_completo"])):  # two true homonyms
            c.tables.append({"id": f"clientes:{row['cliente_id']}", "table": "clientes", "columns": row})
        c.users["UTEST01"] = {"id": "UTEST01", "team_id": "T0", "name": "renata.o", "real_name": LIZCANO["nombre_completo"],
                              "is_bot": False, "is_restricted": False, "tz": "America/Bogota",
                              "profile": {"title": "Cliente", "real_name": LIZCANO["nombre_completo"], "display_name": "renata.o"}}
        for i, t in enumerate(texts):
            c.chats.append({"id": f"m-test-{i}", "thread_id": "t-test", "author": LIZCANO["nombre_completo"],
                            "ts": f"1700000000.00010{i}", "text": t, "attachments": [], "_user": "UTEST01",
                            "_channel": "soporte-test", "_is_bot": False, "_mentions": [], "_deleted_user": False})
        return c

    def owner_of(entities, rec):
        return next(e for e in entities if not e.get("kept") and rec in e["records"])

    eng, ids, *_, before, _ = P.anonymize_corpus(corpus("hola, necesito ayuda con la tarjeta"), tmp_path)
    P.save_state(tmp_path, eng, ids)
    customer = owner_of(before, "clientes:CL-90001")
    split = owner_of(before, "m-test-0")
    assert split["entity_id"] != customer["entity_id"]  # run 1: undecided, the user is its own identity
    # run 2: the thread gains the last four digits of the cédula, so the user is linked
    *_, after, _ = P.anonymize_corpus(corpus("hola, necesito ayuda con la tarjeta", "los últimos 4: 5678"), tmp_path)
    now = owner_of(after, "clientes:CL-90001")
    assert now["entity_id"] == customer["entity_id"]
    assert now["pseudonyms"]["name"] == customer["pseudonyms"]["name"]  # the anchored identity keeps its pseudonym
    assert {"m-test-0", "m-test-1"} <= set(now["records"])
