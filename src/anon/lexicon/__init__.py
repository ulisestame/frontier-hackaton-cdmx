"""Lexicons for the pseudonym factory: names, surnames, places, occupations, stop words.

Raw word lists live in the sibling modules; this module normalizes them once at import
and exposes the derived structures that anon.fakes uses. Everything is stdlib and static,
except register_barrio(), which lets the pipeline add barrios seen in a grown corpus.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

from . import names as _names
from . import occupations as _occ
from . import places as _places
from . import stopwords as _stop
from . import surnames as _sur

_EDGE_PUNCT = re.compile(r"^[\W_]+|[\W_]+$")


@lru_cache(maxsize=1 << 16)
def normalize_token(s: str) -> str:
    """NFKD, strip combining marks, casefold, trim edge punctuation, collapse spaces."""
    if not s:
        return ""
    t = unicodedata.normalize("NFKD", s)
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    t = " ".join(t.split())
    return _EDGE_PUNCT.sub("", t)


def _dedupe(seq):
    seen, out = set(), []
    for x in seq:
        k = normalize_token(x)
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


# ------------------------------------------------------------------ places ---

def _strip_article(n: str) -> str:
    return re.sub(r"^(?:el|la|los|las)\s+", "", n)


CITY_CANON: dict[str, str] = {}
for _city, _aliases in _places.CITY_ALIASES.items():
    for _a in [_city, *_aliases]:
        CITY_CANON[normalize_token(_a)] = _city
for _city in _places.CORPUS_BARRIOS_BY_CITY:
    CITY_CANON.setdefault(normalize_token(_city), _city)


def canonical_city(city: str) -> str:
    """'medellin' -> 'Medellín'; unknown cities come back stripped, unchanged."""
    if not city:
        return ""
    return CITY_CANON.get(normalize_token(city), city.strip())


CORPUS_BARRIOS_BY_CITY: dict[str, list[str]] = {c: list(v) for c, v in _places.CORPUS_BARRIOS_BY_CITY.items()}
BARRIOS_BY_CITY: dict[str, list[str]] = {}
for _city in list(_places.CORPUS_BARRIOS_BY_CITY) + list(_places.EXTRA_BARRIOS_BY_CITY):
    BARRIOS_BY_CITY[_city] = _dedupe(
        _places.CORPUS_BARRIOS_BY_CITY.get(_city, []) + _places.EXTRA_BARRIOS_BY_CITY.get(_city, [])
    )
GENERIC_BARRIOS: list[str] = list(_places.GENERIC_BARRIOS)

# normalized barrio -> cities where the corpus has it (order: first seen)
CITIES_OF_BARRIO: dict[str, list[str]] = {}
for _city, _bs in _places.CORPUS_BARRIOS_BY_CITY.items():
    for _b in _bs:
        CITIES_OF_BARRIO.setdefault(normalize_token(_b), [])
        if _city not in CITIES_OF_BARRIO[normalize_token(_b)]:
            CITIES_OF_BARRIO[normalize_token(_b)].append(_city)
# normalized barrio -> one city. Ambiguous barrios (Castilla: Medellín/Bogotá, Boston:
# Medellín/Barranquilla) map to the first city; prefer the person's own city when known.
CITY_OF_BARRIO: dict[str, str] = {b: cs[0] for b, cs in CITIES_OF_BARRIO.items()}


def register_barrio(city: str, barrio: str) -> None:
    """Add a (city, barrio) pair seen in the live clientes table (the corpus grows)."""
    city_c = canonical_city(city)
    b = (barrio or "").strip()
    nb = normalize_token(b)
    if not city_c or not nb:
        return
    CITY_CANON.setdefault(normalize_token(city_c), city_c)
    corpus = CORPUS_BARRIOS_BY_CITY.setdefault(city_c, [])
    if nb not in {normalize_token(x) for x in corpus}:
        corpus.append(b)
    allb = BARRIOS_BY_CITY.setdefault(city_c, [])
    if nb not in {normalize_token(x) for x in allb}:
        allb.append(b)
    cities = CITIES_OF_BARRIO.setdefault(nb, [])
    if city_c not in cities:
        cities.append(city_c)
    CITY_OF_BARRIO.setdefault(nb, cities[0])


_PLACE_NAMES = (
    [b for bs in BARRIOS_BY_CITY.values() for b in bs]
    + GENERIC_BARRIOS
    + list(_places.CITY_ALIASES)
    + [a for al in _places.CITY_ALIASES.values() for a in al]
    + _places.DEPARTMENTS
    + _places.OTHER_MUNICIPALITIES
)
# single-token place names, exact ("belen", "envigado") and without article ("prado")
PLACE_TOKENS: set[str] = {normalize_token(p) for p in _PLACE_NAMES if " " not in normalize_token(p)}
PLACE_TOKENS_LOOSE: set[str] = PLACE_TOKENS | {
    _strip_article(normalize_token(p)) for p in _PLACE_NAMES
    if " " not in _strip_article(normalize_token(p))
}

# ------------------------------------------------------------------- names ---

GENDER_LEXICON: dict[str, str] = {}
_conflicts: set[str] = set()
for _label, _lists in (("F", (_names.F_COMMON, _names.F_EXTENDED, _names.F_OTHER)),
                       ("M", (_names.M_COMMON, _names.M_EXTENDED, _names.M_OTHER))):
    for _lst in _lists:
        for _n in _lst:
            _k = normalize_token(_n)
            if GENDER_LEXICON.get(_k, _label) != _label:
                _conflicts.add(_k)
            GENDER_LEXICON[_k] = _label
for _k in _conflicts:
    GENDER_LEXICON[_k] = "U"
for _n in _names.UNISEX:
    GENDER_LEXICON[normalize_token(_n)] = "U"

COMPOUND_GENDER: dict[str, str] = dict(_names.COMPOUND_GENDER)
GIVEN_NAMES: frozenset[str] = frozenset(GENDER_LEXICON)
NOT_A_NAME_IN_TEXT: frozenset[str] = frozenset(normalize_token(x) for x in _names.NOT_A_NAME_IN_TEXT)
FAMOUS_PAIRS: frozenset[str] = frozenset(_names.FAMOUS_PAIRS)

SURNAME_LEXICON: frozenset[str] = frozenset(normalize_token(s) for s in _sur.SURNAMES)

_WORDLIKE = {normalize_token(x) for x in _names.WORDLIKE_GIVEN}


def _given_pool(names: list[str], label: str) -> list[str]:
    out = []
    for n in _dedupe(names):
        k = normalize_token(n)
        if GENDER_LEXICON.get(k) != label or k in _WORDLIKE or k in PLACE_TOKENS:
            continue
        if k in SURNAME_LEXICON:  # Alba, Paz, Lara...: keep names and surnames apart
            continue
        if (label == "F") != k.endswith("a"):  # suffix heuristic agrees with the label
            continue
        out.append(n)
    return out


F_POOL_COMMON: list[str] = _given_pool(_names.F_COMMON, "F")
F_POOL_EXTENDED: list[str] = [n for n in _given_pool(_names.F_EXTENDED, "F")
                              if normalize_token(n) not in {normalize_token(x) for x in F_POOL_COMMON}]
M_POOL_COMMON: list[str] = _given_pool(_names.M_COMMON, "M")
M_POOL_EXTENDED: list[str] = [n for n in _given_pool(_names.M_EXTENDED, "M")
                              if normalize_token(n) not in {normalize_token(x) for x in M_POOL_COMMON}]

_NO_GEN_SURNAMES = {normalize_token(x) for x in _sur.SURNAME_NO_GENERATE}
SURNAME_POOL: list[str] = [
    s for s in _dedupe(_sur.SURNAMES)
    if normalize_token(s) not in _NO_GEN_SURNAMES
    and normalize_token(s) not in GENDER_LEXICON
    and normalize_token(s) not in PLACE_TOKENS_LOOSE
]

# -------------------------------------------------------------- occupations ---

SECTOR_PHRASES = dict(_occ.SECTOR_PHRASES)
SECTOR_PHRASES_EN = dict(_occ.SECTOR_PHRASES_EN)
DEFAULT_SECTOR = _occ.DEFAULT_SECTOR
SECTOR_STEMS = list(_occ.SECTOR_STEMS)

# normalized form -> (sector, grammatical gender of the form or None, language)
OCCUPATION_MAP: dict[str, tuple[str, str | None, str]] = {}
_display_terms: list[str] = []


def _parse_occ(spec: str, lang: str) -> None:
    for line in spec.strip().splitlines():
        sector, _, rest = line.partition(":")
        sector = sector.strip()
        if sector not in SECTOR_PHRASES:
            raise ValueError(f"unknown sector {sector!r}")
        for form in rest.split("|"):
            form = form.strip()
            if not form:
                continue
            variants = [(v.strip(), g) for v, g in zip(form.split("/"), ("M", "F"))] if "/" in form else [(form, None)]
            for v, g in variants:
                k = normalize_token(v)
                if k not in OCCUPATION_MAP:
                    OCCUPATION_MAP[k] = (sector, g, lang)
                    _display_terms.append(v)


_parse_occ(_occ.OCCUPATIONS_SPEC, "es")
_parse_occ(_occ.OCCUPATIONS_EN_SPEC, "en")

STAFF_ROLE_TERMS: frozenset[str] = frozenset(normalize_token(x) for x in _occ.STAFF_ROLE_TERMS.split())


def _strip_accents_keep_case(s: str) -> str:
    t = unicodedata.normalize("NFKD", s)
    return unicodedata.normalize("NFC", "".join(c for c in t if not unicodedata.combining(c)))


_terms: list[str] = []
_seen_terms: set[str] = set()
for _t in _display_terms:
    if normalize_token(_t) in STAFF_ROLE_TERMS:
        continue
    for _v in (_t, _strip_accents_keep_case(_t)):
        if _v.casefold() not in _seen_terms:
            _seen_terms.add(_v.casefold())
            _terms.append(_v)
# longest first, so "conductor de plataforma" wins over "conductor"
OCCUPATION_TERMS: list[str] = sorted(_terms, key=lambda t: (-len(t), t))
AMBIGUOUS_OCCUPATION_TERMS: frozenset[str] = frozenset(normalize_token(x) for x in _occ.AMBIGUOUS_TERMS.split())
OCCUPATION_RX = re.compile(
    r"(?<![\w])(?:" + "|".join(re.escape(t) for t in OCCUPATION_TERMS) + r")(?![\w])", re.IGNORECASE
)

# ---------------------------------------------------------------- stop words ---

_stop_raw = (_stop.FUNCTION_WORDS + _stop.DISCOURSE_WORDS + _stop.TITLE_ROLE_WORDS
             + _stop.BUSINESS_WORDS + _stop.BRANDS_ORGS + _stop.PLACES)
NON_NAME_WORDS: frozenset[str] = frozenset(
    {normalize_token(w) for w in _stop_raw}
    - set(GENDER_LEXICON) - set(SURNAME_LEXICON)
    | {normalize_token(w) for w in _stop.MONTHS_DAYS}
    | ({normalize_token(c) for c in CITY_CANON} - set(SURNAME_LEXICON) - set(GENDER_LEXICON))
)

__all__ = [
    "normalize_token", "canonical_city", "register_barrio",
    "BARRIOS_BY_CITY", "CORPUS_BARRIOS_BY_CITY", "GENERIC_BARRIOS", "CITY_OF_BARRIO",
    "CITIES_OF_BARRIO", "CITY_CANON", "PLACE_TOKENS",
    "GENDER_LEXICON", "COMPOUND_GENDER", "GIVEN_NAMES", "NOT_A_NAME_IN_TEXT", "FAMOUS_PAIRS",
    "SURNAME_LEXICON", "F_POOL_COMMON", "F_POOL_EXTENDED", "M_POOL_COMMON", "M_POOL_EXTENDED",
    "SURNAME_POOL", "SECTOR_PHRASES", "SECTOR_PHRASES_EN", "DEFAULT_SECTOR", "SECTOR_STEMS",
    "OCCUPATION_MAP", "OCCUPATION_TERMS", "AMBIGUOUS_OCCUPATION_TERMS", "OCCUPATION_RX",
    "STAFF_ROLE_TERMS", "NON_NAME_WORDS",
]
