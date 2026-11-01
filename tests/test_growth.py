"""A grown corpus: a customer back under a new id, and a PQR whose customer is unknown.

Uses the small sample corpus (data/ is gitignored; the tests skip without it). Every value
these tests add is invented.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from anon.core import pipeline as P
from anon.parse import load_corpus

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "sample" / "input"
pytestmark = pytest.mark.skipif(not SAMPLE.exists(), reason="sample corpus not present")


@pytest.fixture()
def grown(tmp_path):
    eng, ids, *_, before, _ = P.anonymize_corpus(load_corpus(SAMPLE), tmp_path)
    P.save_state(tmp_path, eng, ids)
    corpus = load_corpus(SAMPLE)
    known = next(r for r in corpus.tables if r["table"] == "clientes")
    # the same customer, migrated from another portfolio: new id, new e-mail and phone, same cédula
    migrated = dict(known["columns"], cliente_id="PG-1000", correo="otro.correo@example.com",
                    celular="3009990000", notas="Migrado de otra cartera.")
    corpus.tables.append({"id": "clientes:PG-1000", "table": "clientes", "columns": migrated})
    corpus.tables.append({"id": "pqrs:PQR-2099-0001", "table": "pqrs", "columns": {
        "radicado": "PQR-2099-0001", "cliente_id": "CL-55555", "cedula": "80123456", "ciudad": "Bogotá",
        "fecha": "2099-01-01", "agente": "", "tipo": "queja", "estado": "abierto",
        "descripcion": "No reconozco un cobro.", "respuesta": ""}})
    _, _, _, _, tables, after, _ = P.anonymize_corpus(corpus, tmp_path)
    return known, before, {r["id"]: r["columns"] for r in tables}, after


def test_a_customer_back_under_a_new_id_keeps_the_published_pseudonym(grown):
    known, before, rows, after = grown
    assert rows["clientes:PG-1000"]["nombre_completo"] == rows[known["id"]]["nombre_completo"]
    # one entity: the customer (the known row may also be listed under people its notes mention)
    migrated_owner = {e["entity_id"] for e in after if "clientes:PG-1000" in e["records"]}
    assert len(migrated_owner) == 1
    assert migrated_owner <= {e["entity_id"] for e in after if known["id"] in e["records"]}
    published = {e["entity_id"]: e["pseudonyms"] for e in before if not e.get("kept")}
    assert {e["entity_id"]: e["pseudonyms"] for e in after if e["entity_id"] in published} == published
    for col, raw in (("correo", "otro.correo@example.com"), ("celular", "3009990000")):
        assert rows["clientes:PG-1000"][col] != raw


def test_an_orphan_pqr_cedula_is_replaced(grown):
    _, _, rows, after = grown
    cedula = rows["pqrs:PQR-2099-0001"]["cedula"]
    assert cedula != "80123456" and re.fullmatch(r"\d{8}", cedula)
    assert any("pqrs:PQR-2099-0001" in e["records"] and e["pseudonyms"].get("cedula") == cedula for e in after)
