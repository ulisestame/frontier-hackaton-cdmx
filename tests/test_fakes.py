"""Tests for the deterministic pseudonym factory (anon.fakes) and its lexicons.

Real names are read from data/ when it is present (it is gitignored); a fixed list of
common Colombian name tokens is always blocked so the blocking tests stay meaningful
without the corpus.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import json
import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from anon import fakes as F
from anon import lexicon as L
from anon.fakes import PseudonymFactory, normalize_token

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "fuentes" / "raw"
SAMPLE = ROOT / "data" / "sample"
SECRET = b"test-secret-123"
N = 3000

# Distinct `ocupacion` values of data/fuentes/raw/tables/clientes.csv and of the sample.
CLIENTES_OCCUPATIONS = [
    "comerciante", "contadora", "abogada", "docente", "mecánico", "periodista", "panadero",
    "conductor de plataforma", "chef", "administrador", "ingeniera de sistemas", "piloto comercial",
    "administradora", "abogado", "fisioterapeuta", "ingeniero de sistemas", "arquitecto",
    "estudiante de derecho", "diseñador gráfico", "arquitecta", "veterinario", "enfermera",
    "auxiliar contable", "community manager", "estilista", "ingeniero civil", "electricista",
    "contador", "fotógrafo", "estudiante de medicina", "fotógrafa", "diseñadora gráfica",
    "odontóloga", "psicóloga", "veterinaria",
]
# The reference output of the sample (data/sample/expected_output/tables.jsonl).
SAMPLE_SECTORS = {
    "fotógrafa": "profesional de las industrias creativas",
    "community manager": "profesional de medios",
    "administradora": "profesional de servicios",
    "mecánico": "profesional del transporte",
    "periodista": "profesional de medios",
}
FALLBACK_BLOCKED = """
Alejandra Ana Camila Carlos Daniela Darío Esteban Felipe José Juan Kelly Laura Lucía Luis Manuela María
Mateo Nohora Santiago Sofía Valentina Yesenia
Arango Castaño Gómez Hoyos López Marulanda Martínez Mejía Ospina Pérez Ramírez Restrepo Rodríguez Ruiz
Salazar Velásquez
""".split()


# ------------------------------------------------------------------ fixtures ---

def _real_full_names() -> list[str]:
    names: list[str] = []
    for path in (RAW / "tables" / "clientes.csv", SAMPLE / "input" / "tables" / "clientes.csv"):
        if path.exists():
            text = path.read_bytes().decode("latin-1")
            names += [r["nombre_completo"] for r in csv.DictReader(io.StringIO(text), delimiter=";")]
    emp = RAW / "tables" / "empleados.xml"
    if emp.exists():
        names += [e.findtext("nombre") or "" for e in ET.parse(emp).getroot()]
    for path in (RAW / "chats" / "users.json", SAMPLE / "input" / "chats" / "users.json"):
        if path.exists():
            names += [u.get("real_name") or "" for u in json.loads(path.read_text(encoding="utf-8"))]
    return [n for n in names if n and n.split()]


@pytest.fixture(scope="module")
def blocked() -> set[str]:
    toks = {normalize_token(t) for n in _real_full_names() for t in n.split()}
    return toks | {normalize_token(t) for t in FALLBACK_BLOCKED}


@pytest.fixture(scope="module")
def factory(blocked) -> PseudonymFactory:
    return PseudonymFactory(SECRET, blocked)


@pytest.fixture(scope="module")
def names_3000(factory) -> list[dict]:
    return [factory.name(f"p{i}", "F" if i % 2 else "M", 1 + (i % 3 == 0), 2) for i in range(N)]


def _clientes_rows() -> list[dict]:
    path = RAW / "tables" / "clientes.csv"
    if not path.exists():
        return []
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode("latin-1")), delimiter=";"))


# ------------------------------------------------------------------ determinism ---

def _sample_calls(f: PseudonymFactory) -> list:
    pn = f.name("CL-88627", "F", 1, 2)
    return [
        pn,
        f.name("KP-016", "F", 1, 2),
        f.email("e1", "lbermudez@gmail.com", pn),
        f.email("e2", "paola.quintero@kipupay.co", pn),
        f.cedula("c1", "1.093.418.276"),
        f.phone("t1", "+57 315 604 2817"),
        f.address("a1", "Diagonal 7B # 41-9 apto 1501"),
        f.birth("b1", "1994-05-17"),
        f.plate("pl1", "MQT-582"),
        f.passport("ps1", "AE903614"),
        f.account("ac1", "4111 1111 1111 1111"),
        f.handle("h1", "mquiroga", pn),
        f.pseudo_barrio("CL-88627", "Cali", "Granada"),
    ]


def test_same_secret_and_key_same_output_in_a_new_instance(blocked):
    assert _sample_calls(PseudonymFactory(SECRET, blocked)) == _sample_calls(PseudonymFactory(SECRET, blocked))


def test_different_secret_changes_output(blocked):
    assert _sample_calls(PseudonymFactory(SECRET, blocked)) != _sample_calls(PseudonymFactory(b"other", blocked))


@pytest.mark.parametrize("n,min_stable", [(300, 0.97), (1000, 0.95)])
def test_names_barely_depend_on_call_order(blocked, n, min_stable):
    # Only collisions depend on order; persisted state removes even that.
    keys = [f"p{i}" for i in range(n)]
    a = PseudonymFactory(SECRET, blocked)
    b = PseudonymFactory(SECRET, blocked)
    fwd = {k: a.name(k, "F")["full"] for k in keys}  # one gender: worst case
    rev = {k: b.name(k, "F")["full"] for k in reversed(keys)}
    same = sum(fwd[k] == rev[k] for k in keys)
    assert same / n >= min_stable, same


def test_repeated_call_returns_the_memoized_value(factory):
    first = factory.name("same-key", "F", 2, 2)
    assert factory.name("same-key", "M", 1, 1) == first
    assert factory.cedula("ck", "1093418276") == factory.cedula("ck", "1093418276")


# ------------------------------------------------------------------ uniqueness ---

def test_no_short_form_inside_another_name(names_3000):
    """A person's short form ("Milena Pardo") never appears inside someone else's name
    ("Ana Milena Pardo Ríos"), so the judge cannot attribute records to the wrong person."""
    shorts = {tuple(normalize_token(n["short"]).split()): i for i, n in enumerate(names_3000)}
    for i, n in enumerate(names_3000):
        words = normalize_token(n["full"]).split()
        for a in range(len(words)):
            for b in range(a + 2, len(words) + 1):
                owner = shorts.get(tuple(words[a:b]))
                assert owner in (None, i), (n["full"], names_3000[owner]["short"])


def test_name_pairs_and_forms_unique_over_3000(names_3000):
    shorts = [n["short"] for n in names_3000]
    fulls = [n["full"] for n in names_3000]
    pairs = [(normalize_token(n["given"][0]), normalize_token(n["surnames"][0])) for n in names_3000]
    assert len(set(shorts)) == N
    assert len(set(fulls)) == N
    assert len(set(pairs)) == N


@pytest.mark.parametrize("kind,original", [
    ("cedula", "1093418276"), ("cedula", "41.627.385"), ("phone", "3156042817"),
    ("address", "Calle 87 Bis # 64-21 of 406"), ("plate", "MQT-582"), ("plate", "ABC12D"),
    ("passport", "AE903614"), ("account", "4111111111111111"), ("account", "123-456789-01"),
])
def test_value_kinds_unique_over_3000(factory, kind, original):
    method = getattr(factory, kind)
    out = [method(f"u:{kind}:{original}:{i}", original) for i in range(N)]
    assert len(set(out)) == N
    assert original not in out


@pytest.mark.parametrize("original", ["lbermudez@gmail.com", "paola.quintero@kipupay.co", "lorena.bermudez89@hotmail.com"])
def test_emails_unique_over_3000(factory, names_3000, original):
    out = [factory.email(f"u:email:{original}:{i}", original, names_3000[i]) for i in range(N)]
    assert len(set(out)) == N


@pytest.mark.parametrize("original", ["mquiroga", "andres.villamil"])
def test_handles_unique_over_3000(factory, names_3000, original):
    out = [factory.handle(f"u:handle:{original}:{i}", original, names_3000[i]) for i in range(N)]
    assert len(set(out)) == N


# ------------------------------------------------------------------ blocking ---

def test_blocked_tokens_never_used(factory, names_3000, blocked):
    used = {normalize_token(t) for n in names_3000 for t in n["given"] + n["surnames"]}
    assert not used & blocked
    assert not [t for t in used if factory.is_blocked(t)]  # nor one edit away


def test_pool_sizes_after_blocking(factory):
    sizes = factory.pool_sizes()
    assert sizes["F"] >= 400 and sizes["M"] >= 400 and sizes["surnames"] >= 600, sizes


def test_fuzzy_block_catches_one_edit_variants():
    f = PseudonymFactory(SECRET, {"nathalia", "mejia"})
    assert f.is_blocked("Natalia")    # deletion
    assert f.is_blocked("Nathalie")   # substitution
    assert f.is_blocked("Mejías")     # insertion
    assert not PseudonymFactory(SECRET, {"nathalia"}, fuzzy_block=False).is_blocked("Natalia")


def test_no_famous_or_real_full_name_combination(names_3000):
    pairs = {f"{normalize_token(n['given'][0])}|{normalize_token(n['surnames'][0])}" for n in names_3000}
    assert not pairs & F.FAMOUS_PAIRS


# ------------------------------------------------------------------ names & gender ---

def test_gender_respected_over_the_lexicon(names_3000):
    for i, n in enumerate(names_3000):
        want = "F" if i % 2 else "M"
        assert n["gender"] == want
        for g in n["given"]:
            assert F.GENDER_LEXICON[normalize_token(g)] == want, g
        assert F.guess_gender(n["first"]) == want, n["first"]


def test_name_shape(names_3000):
    for i, n in enumerate(names_3000):
        assert len(n["given"]) == (2 if i % 3 == 0 else 1)
        assert len(n["surnames"]) == 2 and n["surnames"][0] != n["surnames"][1]
        assert n["short"] == " ".join(n["given"] + n["surnames"][:1])
        assert n["first"] == " ".join(n["given"])
        assert all(re.fullmatch(r"[A-ZÁÉÍÓÚÑ][a-záéíóúüñ]+", t) for t in n["given"] + n["surnames"]), n


def test_lexicon_size():
    assert len(F.GENDER_LEXICON) >= 1500
    assert len(F.F_POOL_COMMON) + len(F.F_POOL_EXTENDED) >= 400
    assert len(F.M_POOL_COMMON) + len(F.M_POOL_EXTENDED) >= 400
    assert len(F.SURNAME_POOL) >= 600


@pytest.mark.parametrize("given,gender", [
    ("María José", "F"), ("José María", "M"), ("Kelly", "F"), ("Brayan", "M"), ("Nohora", "F"),
    ("Tomás Felipe", "M"), ("Lorena Paz", "F"), ("Ana Milena", "F"), ("Juan Martín", "M"),
    ("Sra. Pérez", "F"), ("Don Ramiro", "M"), ("LIZETH", "F"), ("andres", "M"), ("Yamid", "M"),
    ("Kipi", None),
])
def test_guess_gender(given, gender):
    assert F.guess_gender(given) == gender


def test_every_real_given_name_is_gendered():
    firsts = {n.split()[0] for n in _real_full_names()} - {"Kipi"}
    if not firsts:
        pytest.skip("corpus not present")
    assert sorted(x for x in firsts if F.guess_gender(x) is None) == []


def test_is_given_name():
    assert F.is_given_name("Darío") and F.is_given_name("PAZ") and F.is_given_name("María José")
    assert not F.is_given_name("Castaño") and not F.is_given_name("Domingo")
    assert not F.is_given_name("Paz", strict=True)
    assert "bancolombia" in F.NON_NAME_WORDS and "julio" in F.NON_NAME_WORDS
    assert "santander" not in F.NON_NAME_WORDS and "castano" not in F.NON_NAME_WORDS


# ------------------------------------------------------------------ formats ---

def _diff(a: str, b: str) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def test_cedula_keeps_formatting_series_and_is_far(factory):
    plain = factory.cedula("ced-k", "1093418276")
    dotted = factory.cedula("ced-k", "1.093.418.276")
    assert re.fullmatch(r"\d{10}", plain) and plain[:2] == "10"
    assert re.fullmatch(r"1\.0\d{2}\.\d{3}\.\d{3}", dotted)
    assert dotted.replace(".", "") == plain  # same person, same digits, original formatting
    assert _diff(plain, "1093418276") >= 5
    for orig in ("45218907", "88.316.042", "70482916", "6840001", "C.C. 63.209.854"):
        out = factory.cedula(f"ced:{orig}", orig)
        assert len(out) == len(orig) and re.sub(r"\d", "0", out) == re.sub(r"\d", "0", orig)
        d_in, d_out = re.sub(r"\D", "", orig), re.sub(r"\D", "", out)
        assert d_out[:2] == d_in[:2] and _diff(d_in, d_out) >= len(d_in) // 2


def test_phone_keeps_formatting_and_is_valid(factory):
    mobile = re.compile(r"3(?:0\d|1\d|2[0-4]|5[01])\d{7}")
    spaced = factory.phone("tel-k", "317 294 5036")
    assert re.fullmatch(r"3\d{2} \d{3} \d{4}", spaced)
    assert mobile.fullmatch(spaced.replace(" ", ""))
    assert _diff(spaced.replace(" ", ""), "3172945036") >= 7
    plus = factory.phone("tel-k2", "+57 320 863 1745")
    assert re.fullmatch(r"\+57 3\d{2} \d{3} \d{4}", plus)
    assert factory.phone("tel-k2", "3208631745") == plus[4:].replace(" ", "")  # same digits
    assert re.fullmatch(r"3\d{2}-\d{3}-\d{4}", factory.phone("tel-k3", "301-458-3927"))
    for i in range(N):
        assert mobile.fullmatch(factory.phone(f"tel:{i}", "3156042817"))


def test_format_like():
    assert F.format_like("1.093.418.276", "1093552810") == "1.093.552.810"
    assert F.format_like("+57 317 294 5036", "573128728322") == "+57 312 872 8322"
    assert F.format_like("41.627.385", "1034857261") == "1.034.857.261"
    assert F.format_like("CC 123", "4567") == "CC 4567"


def test_email_patterns(blocked):
    factory = PseudonymFactory(SECRET, blocked)
    sofia = {"given": ["Sofía", "Elena"], "surnames": ["Zambrano", "Naranjo"]}
    doris = {"given": ["Doris"], "surnames": ["Lozano", "Pardo"]}
    assert re.fullmatch(r"szambrano@(gmail|hotmail|outlook|yahoo|icloud)\.com", factory.email("m1", "lbermudez@gmail.com", sofia))
    assert factory.email("m2", "paola.quintero@kipupay.co", doris) == "doris.lozano@kipupay.co"
    assert re.fullmatch(r"sofia_zambrano@[a-z]+\.com", factory.email("m3", "lorena_bermudez@yahoo.com", sofia))
    digits = factory.email("m4", "lbermudez89@hotmail.com", sofia)
    assert re.fullmatch(r"szambrano\d{2}@[a-z]+\.com", digits) and "89@" not in digits
    spelled = factory.email("m5", "lorena punto bermudez arroba gmail punto com", sofia)
    assert re.fullmatch(r"sofia punto zambrano arroba (gmail|hotmail|outlook|yahoo|icloud) punto com", spelled)
    assert factory.email("m6", "Paola.Quintero@KipuPay.co", doris).endswith("@kipupay.co")
    real = {"given": ["Lorena"], "surnames": ["Bermúdez", "Cuéllar"]}
    assert factory.email("m7", "lbermudezc@gmail.com", sofia, original_name=real).startswith("szambranon@")


def test_emails_are_ascii_lowercase(factory, names_3000):
    rx = re.compile(r"[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]{2,}")
    for i in range(300):
        assert rx.fullmatch(factory.email(f"asc:{i}", "lorena.bermudez@gmail.com", names_3000[i]))


def test_handle_patterns(blocked):
    factory = PseudonymFactory(SECRET, blocked)
    hugo = {"given": ["Hugo"], "surnames": ["Cano", "Valencia"]}
    assert factory.handle("hd1", "andres.villamil", hugo) == "hugo.cano"
    assert factory.handle("hd2", "mquiroga", hugo) == "hcano"


def test_address_style_and_distance(factory):
    rx = re.compile(r"(Calle|Carrera|Diagonal|Transversal|Avenida|Cl|Cra|Dg|Tv|Av)\.? \d{1,3}[A-H]?( Bis)?( Sur)? "
                    r"# \d{1,3}[A-F]?-\d{1,2}( (apto|of|casa|torre|int) \d+)*")
    cases = {
        "Diagonal 7B # 41-9 apto 1501": ("full", "apto"),
        "Calle 87 Bis # 64-21 of 406": ("full", "of"),
        "Tv 138C # 57-24 apto 802": ("abbr", "apto"),
        "Cra 6 Bis # 8-73 casa 52": ("abbr", "casa"),
        "Cl 64 Sur # 27-48 torre 1 apto 803": ("abbr", "torre"),
        "Transversal 31 Bis # 72-85": ("full", None),
    }
    full = ("Calle", "Carrera", "Diagonal", "Transversal", "Avenida")
    for orig, (style, comp) in cases.items():
        out = factory.address(f"addr:{orig}", orig)
        assert rx.fullmatch(out), out
        assert (out.split()[0] in full) == (style == "full"), out
        assert (comp in out.split()) if comp else not re.search(r"\b(apto|of|casa|torre)\b", out), out
        assert re.findall(r"\d+", out)[:3] != re.findall(r"\d+", orig)[:3]
        assert out != orig
    assert rx.fullmatch(factory.address("addr:free", "Km 5 vía Las Palmas"))


def test_birth_formats_and_shift(factory):
    iso = factory.birth("bd", "1994-05-17")
    d0, d1 = dt.date(1994, 5, 17), dt.date.fromisoformat(iso)
    assert 200 <= abs((d1 - d0).days) <= 1500
    assert factory.birth("bd", "17/05/1994") == d1.strftime("%d/%m/%Y")
    months = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
              "octubre", "noviembre", "diciembre"]
    assert factory.birth("bd", "17 de mayo de 1994") == f"{d1.day} de {months[d1.month - 1]} de {d1.year}"
    us = factory.birth("bd2", "DOB 03/26/1984")
    m = re.fullmatch(r"DOB (\d{2})/(\d{2})/(\d{4})", us)
    assert m and dt.date(int(m[3]), int(m[1]), int(m[2]))  # still month-first and valid
    eng = factory.birth("bd3", "May 17, 1994")
    assert re.fullmatch(r"(January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2}, \d{4}", eng)
    year = factory.birth("bd", "nacida en 1994")
    assert year == f"nacida en {d1.year}"
    for i in range(500):
        out = dt.date.fromisoformat(factory.birth(f"bd:{i}", "1990-01-15"))
        assert 200 <= abs((out - dt.date(1990, 1, 15)).days) <= 1500 and out <= F.MAX_BIRTH


def test_plate_passport_account(factory):
    p = factory.plate("pk", "MQT-582")
    assert re.fullmatch(r"[A-Z]{3}-\d{3}", p) and all(a != b for a, b in zip(p, "MQT-582") if b != "-")
    assert re.fullmatch(r"[A-Z]{3}\d{2}[A-Z]", factory.plate("pk2", "ABC12D"))
    assert re.fullmatch(r"[a-z]{3}\d{3}", factory.plate("pk3", "kfy046"))
    ps = factory.passport("psk", "AE903614")
    assert re.fullmatch(r"A[A-Z]\d{6}", ps) and ps != "AE903614"
    card = factory.account("cardk", "4111 1111 1111 1111")
    assert re.fullmatch(r"4\d{3} \d{4} \d{4} \d{4}", card) and F.luhn_valid(card)
    for i in range(500):
        assert F.luhn_valid(factory.account(f"card:{i}", "5500005555555559"))
    acct = factory.account("acctk", "123-456789-01")
    assert re.fullmatch(r"1\d{2}-\d{6}-\d{2}", acct) and acct != "123-456789-01"


def test_slug():
    assert F.slug("Sofía Elena Zambrano") == "sofia_elena_zambrano"
    assert F.slug("  Ñandú  Peña-Gómez ") == "nandu_pena_gomez"


# ------------------------------------------------------------------ state ---

def test_state_roundtrip_keeps_old_pseudonyms_and_avoids_reuse(blocked):
    f1 = PseudonymFactory(SECRET, blocked)
    old = {i: (f1.name(f"p{i}"), f1.cedula(f"c{i}", "1093418276"), f1.email(f"e{i}", "lbermudez@gmail.com", f1.name(f"p{i}")))
           for i in range(1000)}
    state = json.loads(json.dumps(f1.export_state()))
    # new run: more real people blocked, new people first, shuffled order
    f2 = PseudonymFactory(SECRET, blocked | {"stella", "macea"}, state)
    new_keys = list(range(1000, 2000))
    random.Random(7).shuffle(new_keys)
    new = {i: (f2.name(f"p{i}"), f2.cedula(f"c{i}", "1093418276")) for i in new_keys}
    for i in random.Random(3).sample(range(1000), 1000):
        assert f2.name(f"p{i}") == old[i][0]
        assert f2.cedula(f"c{i}", "1093418276") == old[i][1]
        assert f2.email(f"e{i}", "lbermudez@gmail.com", old[i][0]) == old[i][2]
    old_shorts = {v[0]["short"] for v in old.values()}
    assert not old_shorts & {v[0]["short"] for v in new.values()}
    assert not {v[1] for v in old.values()} & {v[1] for v in new.values()}


def test_reserved_real_values_are_never_generated(blocked):
    f1 = PseudonymFactory(SECRET, blocked)
    produced = f1.cedula("rk", "1093418276")
    birth = f1.birth("rk", "1994-05-17")
    f2 = PseudonymFactory(SECRET, blocked, reserved={"cedula": [produced], "birth": [birth]})
    assert f2.cedula("rk", "1093418276") not in (produced, "1093418276")
    assert f2.birth("rk", "1994-05-17") != birth
    # originals seen by the factory are reserved automatically
    f3 = PseudonymFactory(SECRET, blocked)
    f3.birth("x", "1990-01-01")
    assert "1990-01-01" in f3.reserved["birth"]


# ------------------------------------------------------------------ occupations ---

def _all_occupations() -> list[str]:
    values = set(CLIENTES_OCCUPATIONS)
    values |= {r["ocupacion"] for r in _clientes_rows() if r.get("ocupacion")}
    return sorted(values)


@pytest.mark.parametrize("occupation", _all_occupations())
def test_every_clientes_occupation_is_mapped(occupation):
    assert normalize_token(occupation) in F.OCCUPATION_MAP, occupation
    sector = F.occupation_sector(occupation)
    assert sector != "trabajador independiente"
    assert F.occupation_sector(occupation.upper()) == sector
    assert F.occupation_sector(L._strip_accents_keep_case(occupation)) == sector
    assert occupation in F.OCCUPATION_TERMS
    assert F.OCCUPATION_RX.search(f"Yo soy {occupation}, vivo cerca")


def test_sample_reference_sectors():
    for occ, sector in SAMPLE_SECTORS.items():
        assert F.occupation_sector(occ) == sector


def test_occupation_genders_and_fallback():
    assert F.occupation_sector("fotógrafo") == F.occupation_sector("fotógrafa")
    assert F.occupation_sector("astronauta de la NASA") == "trabajador independiente"
    assert F.occupation_sector("costurera de barrio") == "profesional de servicios"
    assert F.occupation_sector("ordeñadora", gender="F") == "trabajadora independiente"
    assert F.occupation_sector("profesional de medios") == "profesional de medios"  # idempotent
    assert F.occupation_sector("photographer") == "creative industries professional"
    assert "asesora" not in F.OCCUPATION_TERMS and "analista" not in F.OCCUPATION_TERMS
    assert "fotografa" in F.OCCUPATION_TERMS  # unaccented chat spelling


# ------------------------------------------------------------------ barrios ---

def test_pseudo_barrio_same_city_and_different():
    for city, barrios in F.CORPUS_BARRIOS_BY_CITY.items():
        allowed = {normalize_token(b) for b in F.BARRIOS_BY_CITY[city]}
        for b in barrios:
            for i in range(40):
                out = F.pseudo_barrio(f"CL-{i}", city, b)
                assert normalize_token(out) in allowed and normalize_token(out) != normalize_token(b)
                assert F.pseudo_barrio(f"CL-{i}", city, b) == out


def test_pseudo_barrio_real_rows_and_aliases():
    rows = _clientes_rows()
    for r in rows:
        out = F.pseudo_barrio(r["cliente_id"], r["ciudad"], r["barrio"])
        assert normalize_token(out) in {normalize_token(b) for b in F.BARRIOS_BY_CITY[r["ciudad"]]}
        assert normalize_token(out) != normalize_token(r["barrio"])
    assert normalize_token(F.pseudo_barrio("k", "medellin", "Envigado")) in {
        normalize_token(b) for b in F.BARRIOS_BY_CITY["Medellín"]}
    unknown = F.pseudo_barrio("k", "Tunja de Prueba", "Centro")
    assert unknown and unknown != "Centro"


def test_city_of_barrio():
    assert F.CITY_OF_BARRIO[normalize_token("Envigado")] == "Medellín"
    assert F.CITY_OF_BARRIO[normalize_token("El Peñón")] == "Cali"
    assert set(F.CITIES_OF_BARRIO["castilla"]) == {"Medellín", "Bogotá"}
    for r in _clientes_rows():
        assert r["ciudad"] in F.CITIES_OF_BARRIO[normalize_token(r["barrio"])]


def test_register_barrio_extends_lists():
    snapshot = (dict(F.CITY_OF_BARRIO), {k: list(v) for k, v in F.CITIES_OF_BARRIO.items()},
                {k: list(v) for k, v in F.BARRIOS_BY_CITY.items()},
                {k: list(v) for k, v in F.CORPUS_BARRIOS_BY_CITY.items()})
    try:
        F.register_barrio("Cali", "Barrio De Prueba Xyz")
        assert F.CITY_OF_BARRIO[normalize_token("Barrio De Prueba Xyz")] == "Cali"
        assert "Barrio De Prueba Xyz" in F.BARRIOS_BY_CITY["Cali"]
        assert "Barrio De Prueba Xyz" in F.CORPUS_BARRIOS_BY_CITY["Cali"]
    finally:
        for live, saved in zip((F.CITY_OF_BARRIO, F.CITIES_OF_BARRIO, F.BARRIOS_BY_CITY,
                                F.CORPUS_BARRIOS_BY_CITY), snapshot):
            live.clear()
            live.update(saved)
