"""Linking chat users to the registry when a name matches more than one person.

Every name, number and address here is invented.
"""

from __future__ import annotations

from types import SimpleNamespace

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
