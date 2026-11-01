"""Regression: bank accounts, card numbers and IPv4 addresses are pseudonymized (invented values)."""

from __future__ import annotations

import re

from anon import fakes
from anon.core.engine import Ctx, Engine

SECRET = b"account-ip-test"


def _engine() -> Engine:
    eng = Engine(fakes.PseudonymFactory(SECRET))
    eng.add_person("cl:1", "customer", "Lorena Cifuentes Bedoya", city="Bogotá")
    eng.f = fakes.PseudonymFactory(SECRET, {"lorena", "cifuentes", "bedoya"})
    return eng


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        x = int(ch) * (2 if i % 2 else 1)
        total += x - 9 if x > 9 else x
    return total % 10 == 0


def _run(eng, text, rid="r1"):
    return eng.anonymize_text(text, Ctx(record_id=rid, owner="cl:1", record_text=text))


def test_bank_account_after_cue_is_replaced_keeping_grouping():
    eng = _engine()
    out = _run(eng, "Le transferí a la cuenta de ahorros 2468 1357 902, de Bancolombia.")
    assert "2468 1357 902" not in out and "24681357902" not in out
    assert re.search(r"cuenta de ahorros \d{4} \d{4} \d{3}, de Bancolombia\.", out)


def test_card_number_fake_is_luhn_valid_and_keeps_grouping():
    eng = _engine()
    original = "4539 1488 0343 6467"
    assert _luhn_ok(original.replace(" ", ""))
    out = _run(eng, f"Mi tarjeta {original} quedó bloqueada.")
    m = re.search(r"tarjeta (\d{4} \d{4} \d{4} \d{4}) quedó", out)
    assert m and m.group(1) != original
    assert _luhn_ok(m.group(1).replace(" ", ""))


def test_same_account_same_fake_across_records():
    eng = _engine()
    a = _run(eng, "Pago desde la cuenta 1122334455667.", "r1")
    b = _run(eng, "Transferencia a cuenta 1122334455667 recibida.", "r2")
    assert re.search(r"\d{13}", a).group() == re.search(r"\d{13}", b).group()


def test_last_four_digits_and_obligation_numbers_stay():
    eng = _engine()
    text = "La tarjeta terminada en 7777 tiene la obligación 7310-0042 al día."
    assert _run(eng, text) == text


def test_ipv4_is_replaced_consistently_and_versions_stay():
    eng = _engine()
    a = _run(eng, "Transferencia desde IP 203.0.113.45 a las 3am.", "r1")
    b = _run(eng, "Misma IP 203.0.113.45 en el segundo intento.", "r2")
    assert "203.0.113.45" not in a and "203.0.113.45" not in b
    fake = re.search(r"\d{1,3}(?:\.\d{1,3}){3}", a).group()
    assert all(0 <= int(x) <= 255 for x in fake.split("."))
    assert fake in b
    assert _run(eng, "Generado con Editor 2.7 el 2030-01-15.", "r3") == "Generado con Editor 2.7 el 2030-01-15."


def test_account_with_the_bank_named_between_cue_and_number():
    eng = _engine()
    out = _run(eng, "¿Les sirve la cuenta de Bancolombia? Es la 13579246801, de ahí sale el pago.")
    assert "13579246801" not in out and "Bancolombia" in out
    assert re.search(r"Es la \d{11}, de ahí", out)


def test_large_amount_after_cuenta_is_not_an_account():
    eng = _engine()
    text = "La cuenta recibió 1.250.000.000 pesos del fondo."
    assert _run(eng, text) == text


def test_insurance_policy_numbers_are_replaced_keeping_format():
    eng = _engine()
    out = _run(eng, "Débito de la póliza Seguros Andinos 2071834 aplicado; pago póliza Sura 55-12345.")
    assert "2071834" not in out and "55-12345" not in out
    assert re.search(r"póliza Seguros Andinos \d{7} aplicado; pago póliza Sura \d{2}-\d{5}\.", out)


def test_policy_cue_does_not_reach_keys_obligations_or_pse_references():
    eng = _engine()
    text = ("Débito automático de póliza mensual activo, petición PQR-2099-0001 cerrada; "
            "la póliza del crédito 7310-0042 sigue; pago póliza PSE-11112222 confirmado.")
    assert _run(eng, text) == text
