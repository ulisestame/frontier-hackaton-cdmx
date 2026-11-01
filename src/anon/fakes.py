"""Deterministic pseudonym factory.

Every random choice comes from HMAC-SHA256(secret, "<kind>:<key>:<slot>:<attempt>#<n>"),
so the same (secret, key, original) always yields the same pseudonym, in any process,
with no global random state. Collisions with pseudonyms already handed out (``taken``)
or with real values (``reserved``) bump ``attempt``.

Names are drawn with consistent hashing (a hash ring per pool): blocking a token or
editing a pool only changes the people whose pick was that token, everyone else keeps
their pseudonym. Persist ``export_state()`` between runs and pass it back as ``state``
so people already published keep exactly the same pseudonyms and new people never reuse
them.
"""

from __future__ import annotations

import bisect
import datetime as _dt
import hashlib
import hmac
import re
import unicodedata
from collections import defaultdict
from typing import Callable, Iterable, Mapping

from .lexicon import (
    AMBIGUOUS_OCCUPATION_TERMS,
    BARRIOS_BY_CITY,
    CITIES_OF_BARRIO,
    CITY_OF_BARRIO,
    COMPOUND_GENDER,
    CORPUS_BARRIOS_BY_CITY,
    DEFAULT_SECTOR,
    F_POOL_COMMON,
    F_POOL_EXTENDED,
    FAMOUS_PAIRS,
    GENDER_LEXICON,
    GENERIC_BARRIOS,
    GIVEN_NAMES,
    M_POOL_COMMON,
    M_POOL_EXTENDED,
    NON_NAME_WORDS,
    NOT_A_NAME_IN_TEXT,
    OCCUPATION_MAP,
    OCCUPATION_RX,
    OCCUPATION_TERMS,
    SECTOR_PHRASES,
    SECTOR_PHRASES_EN,
    SECTOR_STEMS,
    SURNAME_LEXICON,
    SURNAME_POOL,
    canonical_city,
    normalize_token,
    register_barrio,
)

__all__ = [
    "PseudonymFactory", "normalize_token", "format_like", "slug", "guess_gender",
    "is_given_name", "occupation_sector", "pseudo_barrio", "canonical_city", "register_barrio",
    "luhn_valid", "OCCUPATION_TERMS", "OCCUPATION_RX", "AMBIGUOUS_OCCUPATION_TERMS",
    "CITY_OF_BARRIO", "CITIES_OF_BARRIO", "BARRIOS_BY_CITY", "CORPUS_BARRIOS_BY_CITY",
    "NON_NAME_WORDS", "PUBLIC_EMAIL_PROVIDERS", "PUBLIC_EMAIL_DOMAINS", "MOBILE_PREFIXES",
]

STATE_VERSION = 1
PUBLIC_EMAIL_PROVIDERS = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com")
PUBLIC_EMAIL_DOMAINS = frozenset(PUBLIC_EMAIL_PROVIDERS) | frozenset({
    "live.com", "msn.com", "aol.com", "me.com", "mac.com", "mail.com", "protonmail.com",
    "proton.me", "gmx.com", "zoho.com", "hotmail.es", "outlook.es", "yahoo.es", "yahoo.com.co",
    "hotmail.co", "gmail.co", "live.com.co", "outlook.com.co", "hotmail.com.co", "yahoo.com.mx",
    "googlemail.com", "ymail.com", "rocketmail.com", "une.net.co", "etb.net.co",
})
# Colombian mobile operator prefixes.
MOBILE_PREFIXES = tuple(str(p) for p in [*range(300, 325), 350, 351])
# Latest plausible birth date for an adult customer of the corpus (18 years before 2026-12-31).
MAX_BIRTH = _dt.date(2008, 12, 31)

_DIGITS = "0123456789"
_PLATE_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"  # no I/O/Q: they read as digits
_PLATE_STOP = {"USD", "COP", "EUR", "MXN", "PQR", "INC", "CEO", "CTO", "CFO", "COO", "API", "PDF",
               "IVA", "GMF", "SOS", "ONU", "FBI", "SIC", "PSE", "KIP", "DNI", "NIT", "CCC", "XXX"}
_MAX_ATTEMPTS = 500


# ---------------------------------------------------------------- text utils ---

def _fold(s: str) -> str:
    """Lowercase, accents and ñ stripped, everything else kept (for emails/handles)."""
    t = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in t if not unicodedata.combining(c)).casefold()


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(s))


def _only_digits(s: str) -> str:
    return "".join(c for c in str(s or "") if c in _DIGITS)


def slug(text: str) -> str:
    """'Sofía Elena Zambrano' -> 'sofia_elena_zambrano' (lowercase ASCII, underscores)."""
    return re.sub(r"[^a-z0-9]+", "_", _fold(text)).strip("_")


def format_like(original: str, new_digits: str) -> str:
    """Write new_digits into the digit positions of original, keeping every other character.

    '1.093.418.276' + '1093552810' -> '1.093.552.810'; '+57 317 294 5036' keeps '+57 '.
    With a different digit count the original prefix/suffix are kept and, if the original
    grouped digits uniformly ('1.234.567'), the new digits are regrouped the same way.
    """
    nd = _only_digits(new_digits)
    orig = str(original or "")
    n = sum(1 for c in orig if c in _DIGITS)
    if n == len(nd):
        it = iter(nd)
        return "".join(next(it) if c in _DIGITS else c for c in orig)
    if n == 0:
        return nd
    first = next(i for i, c in enumerate(orig) if c in _DIGITS)
    last = max(i for i, c in enumerate(orig) if c in _DIGITS)
    prefix, body, suffix = orig[:first], orig[first:last + 1], orig[last + 1:]
    groups, seps = re.findall(r"\d+", body), re.findall(r"\D+", body)
    if seps and len(set(seps)) == 1 and len(groups) > 1 and all(len(g) == len(groups[-1]) for g in groups[1:]):
        size, sep, parts, rest = len(groups[-1]), seps[0], [], nd
        while len(rest) > size:
            parts.insert(0, rest[-size:])
            rest = rest[:-size]
        parts.insert(0, rest)
        return prefix + sep.join(parts) + suffix
    return prefix + nd + suffix


def _alnum_like(original: str, new: str) -> str:
    """Write new (A-Z0-9) into the ASCII alphanumeric positions of original, keeping case."""
    it = iter(new)
    out = []
    for c in original:
        if c.isascii() and c.isalnum():
            n = next(it, "")
            out.append(n.lower() if c.islower() else n)
        else:
            out.append(c)
    return "".join(out) + "".join(it)


def luhn_valid(number: str) -> bool:
    d = _only_digits(number)
    if len(d) < 2:
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        v = int(ch)
        if i % 2 == 1:
            v = v * 2 - 9 if v > 4 else v * 2
        total += v
    return total % 10 == 0


def _luhn_digit(payload: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(payload)):
        v = int(ch)
        if i % 2 == 0:
            v = v * 2 - 9 if v > 4 else v * 2
        total += v
    return str((10 - total % 10) % 10)


def _coerce_gender(g) -> str | None:
    if not g:
        return None
    k = normalize_token(str(g))
    if k in ("f", "fem", "female", "femenino", "mujer", "w", "woman"):
        return "F"
    if k in ("m", "masc", "male", "masculino", "hombre", "man"):
        return "M"
    return None


# ---------------------------------------------------------------- determinism ---

class _Rand:
    """Deterministic stream: HMAC-SHA256(secret, msg + '#' + counter)."""

    __slots__ = ("_key", "_msg", "_ctr", "_buf")

    def __init__(self, key: bytes, msg: str):
        self._key, self._msg, self._ctr, self._buf = key, msg.encode("utf-8"), 0, b""

    def bits(self) -> int:
        if len(self._buf) < 8:
            self._buf += hmac.new(self._key, self._msg + b"#" + str(self._ctr).encode(), hashlib.sha256).digest()
            self._ctr += 1
        out, self._buf = self._buf[:8], self._buf[8:]
        return int.from_bytes(out, "big")

    def below(self, n: int) -> int:
        if n <= 1:
            return 0
        limit = (1 << 64) - ((1 << 64) % n)
        while True:
            x = self.bits()
            if x < limit:
                return x % n

    def between(self, lo: int, hi: int) -> int:
        return lo + self.below(hi - lo + 1)

    def choice(self, seq):
        return seq[self.below(len(seq))]

    def chance(self, p: float) -> bool:
        return self.bits() < int(p * (1 << 64))


def _hmac_int(key: bytes, msg: str) -> int:
    return int.from_bytes(hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()[:8], "big")


class _Ring:
    """Consistent-hash ring over a name pool (64 virtual nodes per name)."""

    VNODES = 64

    def __init__(self, items: Iterable[str]):
        pts = []
        for it in items:
            k = normalize_token(it)
            for v in range(self.VNODES):
                h = int.from_bytes(hashlib.blake2b(f"{k}#{v}".encode(), digest_size=8).digest(), "big")
                pts.append((h, it))
        pts.sort()
        self.points = [p for p, _ in pts]
        self.items = [it for _, it in pts]

    def walk(self, seed: int, accept: Callable[[str], bool]) -> str | None:
        n = len(self.points)
        i = bisect.bisect_left(self.points, seed)
        seen: set[str] = set()
        for k in range(n):
            it = self.items[(i + k) % n]
            if it in seen:
                continue
            seen.add(it)
            if accept(it):
                return it
        return None


_RINGS: dict | None = None


def _rings() -> dict:
    global _RINGS
    if _RINGS is None:
        _RINGS = {
            "F": {"common": _Ring(F_POOL_COMMON), "extended": _Ring(F_POOL_EXTENDED)},
            "M": {"common": _Ring(M_POOL_COMMON), "extended": _Ring(M_POOL_EXTENDED)},
            "S": _Ring(SURNAME_POOL),
        }
    return _RINGS


class _Blocklist:
    """Real name tokens. With fuzzy=True a candidate one edit away (insert, delete,
    substitute, adjacent swap) from a blocked token of 4+ letters is blocked too."""

    def __init__(self):
        self.exact: set[str] = set()
        self._dels: set[str] = set()
        self._subs: set[tuple[str, int]] = set()
        self._cache: dict[tuple[str, bool], bool] = {}

    def add(self, token: str) -> None:
        for part in re.split(r"[\s\-'’]+", normalize_token(token)):
            if not part or part in self.exact:
                continue
            self.exact.add(part)
            if len(part) >= 4:
                for i in range(len(part)):
                    d = part[:i] + part[i + 1:]
                    self._dels.add(d)
                    self._subs.add((d, i))
            self._cache.clear()

    def hit(self, token: str, fuzzy: bool) -> bool:
        t = normalize_token(token)
        key = (t, fuzzy)
        r = self._cache.get(key)
        if r is None:
            r = any(self._hit(p, fuzzy) for p in re.split(r"[\s\-'’]+", t) if p)
            self._cache[key] = r
        return r

    def _hit(self, c: str, fuzzy: bool) -> bool:
        if c in self.exact:
            return True
        if not fuzzy or len(c) < 3:
            return False
        if c in self._dels:
            return True
        for i in range(len(c)):
            d = c[:i] + c[i + 1:]
            if (len(d) >= 4 and d in self.exact) or (d, i) in self._subs:
                return True
        for i in range(len(c) - 1):
            sw = c[:i] + c[i + 1] + c[i] + c[i + 2:]
            if sw != c and len(sw) >= 4 and sw in self.exact:
                return True
        return False


# ---------------------------------------------------------------- module-level ---

_TITLES_F = {"sra", "senora", "srta", "senorita", "dona", "dra", "doctora", "ingeniera", "licenciada",
             "profesora", "mrs", "ms", "miss", "madam"}
_TITLES_M = {"sr", "senor", "don", "dr", "doctor", "ingeniero", "licenciado", "profesor", "mr", "sir"}


def _suffix_gender(t: str) -> str | None:
    if len(t) < 2:
        return None
    if t.endswith(("cion", "sion", "bel", "quel")):
        return "F"
    if t.endswith(("a", "th", "ys", "ine", "ette", "elle")):
        return "F"
    if t.endswith(("o", "os", "or", "er", "el", "on", "an", "in", "us", "id", "ul", "ur", "ar", "ir", "ton", "son")):
        return "M"
    return None


def guess_gender(given_name: str) -> str | None:
    """'María José' -> 'F', 'José María' -> 'M', 'Kelly' -> 'F'; None when it cannot tell.

    Lexicon first (compound names, then token by token skipping unisex names), titles such
    as "Sra." / "Don", and suffix heuristics only as a last resort.
    """
    toks = [t for t in (normalize_token(x) for x in re.split(r"[\s,]+", given_name or "")) if t]
    if not toks:
        return None
    if toks[0] in _TITLES_F:
        return "F"
    if toks[0] in _TITLES_M:
        return "M"
    for n in range(min(len(toks), 5), 1, -1):
        c = " ".join(toks[:n])
        if c in COMPOUND_GENDER:
            return COMPOUND_GENDER[c]
    for i, t in enumerate(toks):
        g = GENDER_LEXICON.get(t)
        if g in ("F", "M"):
            return g
        if g is None and i > 0 and t not in SURNAME_LEXICON:
            break  # an unknown word after the first one: stop, do not read surnames as names
    return _suffix_gender(toks[0]) if toks[0] not in GENDER_LEXICON else None


def is_given_name(token: str, strict: bool = False) -> bool:
    """True when token is a known given name. Words that read as plain words in running
    text (Domingo, Santos, Cruz...) answer False. strict=True also rejects tokens that are
    common surnames (Paz, León, Franco...)."""
    t = normalize_token(token)
    if not t:
        return False
    if " " in t:
        return all(is_given_name(x, strict) for x in t.split())
    if t in NOT_A_NAME_IN_TEXT:
        return False
    if strict and t in SURNAME_LEXICON:
        return False
    return t in GIVEN_NAMES


_SECTOR_BY_PHRASE = {normalize_token(p): k for k, (m, f) in SECTOR_PHRASES.items() for p in (m, f)}
_SECTOR_BY_PHRASE.update({normalize_token(p): k for k, p in SECTOR_PHRASES_EN.items()})
_EN_PHRASES = {normalize_token(p) for p in SECTOR_PHRASES_EN.values()}
_INVARIABLE_ENDINGS = ("ista", "eta", "ata", "auta", "atra", "crata", "cida", "ita", "ega", "arca", "ante", "ente", "iente", "e")
_EN_HINTS = {"engineer", "driver", "worker", "manager", "designer", "teacher", "nurse", "student",
             "owner", "assistant", "developer", "officer", "analyst", "consultant", "technician"}


def _form_gender(k: str) -> str | None:
    head = k.split()[0] if k else ""
    if not head or head.endswith(_INVARIABLE_ENDINGS):
        return None
    if head.endswith("a"):
        return "F"
    if head.endswith(("o", "or", "an", "in")):
        return "M"
    return None


def occupation_sector(occupation: str, gender: str | None = None) -> str:
    """Generalize an occupation to a sector phrase: 'fotógrafa' -> 'profesional de las
    industrias creativas', 'mecánico' -> 'profesional del transporte'. Case and accent
    insensitive; unknown -> 'trabajador independiente' ('trabajadora' when the form or the
    gender says F). English terms get English sector phrases."""
    k = normalize_token(occupation)
    if not k:
        return ""
    k = re.sub(r"^(?:yo\s+)?(?:soy|trabajo\s+como|un|una|el|la|i\s+am\s+an?|i'm\s+an?|an?)\s+", "", k)
    if k in _SECTOR_BY_PHRASE:  # already generalized: idempotent
        sector, lang = _SECTOR_BY_PHRASE[k], ("en" if k in _EN_PHRASES else "es")
        masc, fem = SECTOR_PHRASES[sector]
        form_g = "F" if (k == normalize_token(fem) and fem != masc) else None
    elif k in OCCUPATION_MAP:
        sector, form_g, lang = OCCUPATION_MAP[k]
    elif (hit := OCCUPATION_RX.search(k)) and normalize_token(hit.group()) in OCCUPATION_MAP:
        sector, form_g, lang = OCCUPATION_MAP[normalize_token(hit.group())]  # "costurera de barrio"
    else:
        sector = next((s for stem, s in SECTOR_STEMS if stem in k), DEFAULT_SECTOR)
        form_g = _form_gender(k)
        lang = "en" if set(k.split()) & _EN_HINTS else "es"
    if lang == "en":
        return SECTOR_PHRASES_EN[sector]
    g = _coerce_gender(gender) or form_g
    masc, fem = SECTOR_PHRASES[sector]
    return fem if g == "F" else masc


_BARRIO_SALT = b"anon.fakes.barrio.v1"


def pseudo_barrio(key: str, city: str, original_barrio: str, secret: bytes | None = None) -> str:
    """Another barrio of the same city, deterministic per (key, city, barrio), never the
    original. Half the time from the barrios the corpus itself uses for that city, half from
    other well-known barrios of the city (rendezvous hashing, so adding barrios later only
    moves the keys the new barrio wins). Unknown city -> a generic Colombian barrio name."""
    orig = normalize_token(original_barrio)
    if not orig:
        return original_barrio or ""
    city_c = canonical_city(city)
    if city_c not in BARRIOS_BY_CITY and orig in CITY_OF_BARRIO:
        city_c = CITY_OF_BARRIO[orig]
    corpus = [b for b in CORPUS_BARRIOS_BY_CITY.get(city_c, []) if normalize_token(b) != orig]
    corpus_n = {normalize_token(b) for b in corpus}
    extra = [b for b in BARRIOS_BY_CITY.get(city_c, []) if normalize_token(b) not in corpus_n | {orig}]
    if not corpus and not extra:
        extra = [b for b in GENERIC_BARRIOS if normalize_token(b) != orig]
    k = secret or _BARRIO_SALT
    base = f"barrio:{key}:{normalize_token(city_c)}:{orig}"
    use_corpus = bool(corpus) and (not extra or _hmac_int(k, base + ":tier") % 2 == 0)
    tier = corpus if use_corpus else extra
    return max(tier, key=lambda b: _hmac_int(k, f"{base}:{normalize_token(b)}"))


# ---------------------------------------------------------------- emails/handles ---

_SPELLED_AT = re.compile(r"\s+(arroba|at)\s+", re.I)
_SP_US = re.compile(r"\s+(gui[oó]n\s+bajo|underscore|raya\s+al\s+piso)\s+", re.I)
_SP_DASH = re.compile(r"\s+(gui[oó]n|raya|dash|hyphen)\s+", re.I)
_SP_DOT = re.compile(r"\s+(punto|dot)\s+", re.I)
_LOCAL_TOKENS = re.compile(r"[a-z]+|[0-9]+|[^a-z0-9]+")


def _parse_email(original: str) -> tuple[str, str, dict | None]:
    s = (original or "").strip()
    if "@" in s:
        local, _, domain = s.rpartition("@")
        return _fold(local).strip(), _fold(domain).strip(), None
    m = _SPELLED_AT.search(s)
    if m:
        lp, dp = s[:m.start()], s[m.end():]
        english = m.group(1).lower() == "at"
        style = {"at": m.group(1), "upper": s.isupper()}
        mm = _SP_DOT.search(lp) or _SP_DOT.search(dp)
        style["dot"] = mm.group(1) if mm else ("dot" if english else "punto")
        mm = _SP_US.search(lp)
        style["us"] = mm.group(1) if mm else ("underscore" if english else "guion bajo")
        mm = _SP_DASH.search(_SP_US.sub("_", lp))
        style["dash"] = mm.group(1) if mm else ("dash" if english else "guion")
        local = _SP_DOT.sub(".", _SP_DASH.sub("-", _SP_US.sub("_", lp)))
        domain = _SP_DOT.sub(".", dp)
        return re.sub(r"\s+", "", _fold(local)), re.sub(r"\s+", "", _fold(domain)), style
    return re.sub(r"\s+", "", _fold(s)), "", None


def _style_email(email: str, style: dict | None) -> str:
    if not style:
        return email
    local, _, domain = email.partition("@")
    loc = local.replace("_", f" {style['us']} ").replace("-", f" {style['dash']} ").replace(".", f" {style['dot']} ")
    out = f"{loc} {style['at']} {domain.replace('.', ' ' + style['dot'] + ' ')}"
    return out.upper() if style.get("upper") else out


def _split_name(name) -> tuple[list[str], list[str]]:
    """Accepts a factory name dict, {'given': [...], 'surnames': [...]}, or a string."""
    if not name:
        return [], []
    if isinstance(name, Mapping):
        g = list(name.get("given") or [])
        s = list(name.get("surnames") or [])
        if not g and name.get("full"):
            return _split_name(str(name["full"]))
        return [x for w in g for x in str(w).split()], [x for w in s for x in str(w).split()]
    toks = str(name).split()
    if len(toks) >= 4:
        return toks[:2], toks[2:]
    if len(toks) == 3:
        return (toks[:2], toks[2:]) if is_given_name(toks[1], strict=True) else (toks[:1], toks[1:])
    return toks[:1], toks[1:]


def _explain_with_name(tok: str, given: list[str], surnames: list[str]):
    atoms = []
    for i, g in enumerate(given):
        if g:
            atoms += [("G", i, g), ("g", i, g[0])]
    for j, s in enumerate(surnames):
        if s:
            atoms += [("S", j, s), ("s", j, s[0])]
    n = len(tok)
    best: list = [None] * (n + 1)
    best[0] = (0, [])
    for pos in range(n):
        if best[pos] is None:
            continue
        cost, path = best[pos]
        for typ, idx, text in atoms:
            if tok.startswith(text, pos):
                np_ = pos + len(text)
                c = cost + (3 if typ in "gs" else 1)
                if best[np_] is None or c < best[np_][0]:
                    best[np_] = (c, path + [("A", typ, idx)])
    return best[n][1] if best[n] else None


def _local_template(local: str, original_name=None, blocked: set[str] | frozenset = frozenset()) -> list:
    """Describe a local part / handle as atoms: G/g given name or initial, S/s surname or
    initial (with index), D digits, L literal separators."""
    loc = _fold(local)
    toks = _LOCAL_TOKENS.findall(loc)
    alpha = [i for i, t in enumerate(toks) if t.isalpha()]
    m = len(alpha)
    og, os_ = _split_name(original_name)
    og, os_ = [_alnum(x) for x in og], [_alnum(x) for x in os_]

    def known_given(x):
        return x in GIVEN_NAMES

    def known_surname(x):
        return x in SURNAME_LEXICON or (x in blocked and x not in GIVEN_NAMES)

    parts: list = []
    gi = si = 0
    prev = None
    for idx, t in enumerate(toks):
        if t.isdigit():
            parts.append(("D", t))
            continue
        if not t.isalpha():
            parts.append(("L", t))
            continue
        k = alpha.index(idx)
        atoms = _explain_with_name(t, og, os_) if (og or os_) else None
        if atoms is None:
            if m == 1:
                if len(t) >= 4 and known_surname(t[1:]):
                    atoms = [("A", "g", 0), ("A", "S", 0)]
                elif len(t) >= 5 and known_surname(t[1:-1]):
                    atoms = [("A", "g", 0), ("A", "S", 0), ("A", "s", 1)]
                else:
                    split = next((p for p in range(len(t) - 3, 1, -1)
                                  if known_given(t[:p]) and known_surname(t[p:])), None)
                    if split:
                        atoms = [("A", "G", 0), ("A", "S", 0)]
                    elif known_given(t):
                        atoms = [("A", "G", 0)]
                    elif known_surname(t):
                        atoms = [("A", "S", 0)]
                    elif len(t) >= 4 and known_given(t[:-1]):
                        atoms = [("A", "G", 0), ("A", "s", 0)]
                    else:
                        atoms = [("A", "g", 0), ("A", "S", 0)]
            elif len(t) == 1:
                if k == 0:
                    atoms = [("A", "g", gi)]
                    gi += 1
                elif k == m - 1 and prev in ("G", "g") and si == 0:
                    atoms = [("A", "s", si)]
                    si += 1
                elif si == 0:
                    atoms = [("A", "g", gi)]
                    gi += 1
                else:
                    atoms = [("A", "s", si)]
                    si += 1
            elif len(t) == 2 and k == 0 and not known_given(t):
                atoms = [("A", "g", 0), ("A", "g", 1)]
                gi = 2
            elif known_surname(t) and not (k == 0 and known_given(t)):
                atoms = [("A", "S", si)]
                si += 1
            elif known_given(t) and si == 0:
                atoms = [("A", "G", gi)]
                gi += 1
            elif k == 0:
                atoms = [("A", "G", gi)]
                gi += 1
            elif k == m - 1 or si > 0:
                atoms = [("A", "S", si)]
                si += 1
            else:
                atoms = [("A", "G", gi)]
                gi += 1
        parts.extend(atoms)
        prev = atoms[-1][1] if atoms else prev
    return parts


def _new_digits(orig: str, r: _Rand) -> str:
    if len(orig) == 4 and orig[:2] in ("19", "20"):
        years = [y for y in range(1955, 2009) if str(y) != orig]
        return str(r.choice(years))
    return "".join(r.choice([d for d in _DIGITS if d != c]) for c in orig)


def _render_local(parts: list, given: list[str], surnames: list[str], r: _Rand, variant: int) -> str:
    pieces: list[tuple[str, str]] = []
    for p in parts:
        if p[0] == "L":
            pieces.append(("L", p[1]))
        elif p[0] == "D":
            pieces.append(("T", _new_digits(p[1], r)))
        else:
            _, typ, idx = p
            src = given if typ in "Gg" else surnames
            if idx >= len(src) or not _alnum(src[idx]):
                pieces.append(("X", ""))
                continue
            tok = _alnum(src[idx])
            pieces.append(("T", tok if typ in "GS" else tok[0]))
    out: list[str] = []
    pending_sep = ""
    for kind, text in pieces:
        if kind == "L":
            pending_sep = pending_sep or text
        elif kind == "X":
            continue
        else:
            if out and pending_sep:
                out.append(pending_sep)
            out.append(text)
            pending_sep = ""
    s = "".join(out).strip("._-")
    if variant > 0 and not any(p[0] == "D" for p in parts):
        s += str(r.between(10, 99))
    return s


# ---------------------------------------------------------------- addresses ---

_VIA_CANON = {
    "calle": "calle", "cl": "calle", "cll": "calle", "clle": "calle", "call": "calle",
    "carrera": "carrera", "cra": "carrera", "cr": "carrera", "kr": "carrera", "kra": "carrera",
    "crr": "carrera", "carr": "carrera", "cra.": "carrera",
    "diagonal": "diagonal", "dg": "diagonal", "diag": "diagonal",
    "transversal": "transversal", "tv": "transversal", "tr": "transversal", "trans": "transversal",
    "transv": "transversal", "tranv": "transversal", "trv": "transversal",
    "avenida": "avenida", "av": "avenida", "avda": "avenida", "avd": "avenida",
    "ac": "avenida calle", "ak": "avenida carrera",
    "circular": "circular", "cq": "circular", "circunvalar": "circunvalar", "autopista": "autopista",
}
_VIA_FULL_WORDS = {"calle", "carrera", "diagonal", "transversal", "avenida", "circular", "circunvalar", "autopista"}
_VIA_TYPES = ["calle"] * 7 + ["carrera"] * 7 + ["diagonal"] * 2 + ["transversal"] * 2 + ["avenida"] * 2
_VIA_FULL = {"calle": "Calle", "carrera": "Carrera", "diagonal": "Diagonal", "transversal": "Transversal", "avenida": "Avenida"}
_VIA_ABBR = {"calle": "Cl", "carrera": "Cra", "diagonal": "Dg", "transversal": "Tv", "avenida": "Av"}

_ADDR_RX = re.compile(
    r"""^(?P<lead>\s*)
    (?P<via>[A-Za-zÁÉÍÓÚáéíóúÑñ]+\.?(?:\s+(?:calle|carrera|cra\.?|cl\.?|kr\.?)(?=\s))?)
    (?P<s1>\s+)
    (?P<num>\d{1,3})(?P<let>\s?[A-Za-z](?![A-Za-z]))?(?P<bis>\s+bis\b)?(?P<let2>\s?[A-Za-z](?![A-Za-z]))?
    (?P<card>\s+(?:sur|este|norte|oeste)\b)?
    (?P<sep>\s*(?:\#|No\.?|N[°º]\.?|Nro\.?|Num\.?|N[úu]mero)\s*)
    (?P<cross>\d{1,3})(?P<clet>\s?[A-Za-z](?![A-Za-z]))?(?P<cbis>\s+bis\b)?
    (?P<dash>\s*-\s*)
    (?P<house>\d{1,3})(?P<card2>\s+(?:sur|este|norte|oeste)\b)?
    (?P<rest>.*)$""",
    re.X | re.I | re.S,
)
_COMP_RX = re.compile(
    r"(?P<pre>\s*,?\s*)(?P<kw>apartamento|apto|apt|ap|oficina|ofic|of|consultorio|cons|casa|cs|interior|int|"
    r"local|loc|bodega|piso|torre|bloque|blq|bl|etapa|manzana|mz|lote|lt)(?P<dot>\.?)(?P<mid>\s*)"
    r"(?P<val>\d{1,4}[A-Za-z]?|[A-Za-z])(?![\w])",
    re.I,
)
_COMP_CANON = {
    "apartamento": "apto", "apto": "apto", "apt": "apto", "ap": "apto", "oficina": "of", "ofic": "of",
    "of": "of", "consultorio": "of", "cons": "of", "casa": "casa", "cs": "casa", "interior": "int",
    "int": "int", "local": "local", "loc": "local", "bodega": "local", "piso": "piso", "torre": "torre",
    "bloque": "bloque", "blq": "bloque", "bl": "bloque", "etapa": "etapa", "manzana": "mz", "mz": "mz",
    "lote": "lote", "lt": "lote",
}


def _case_like(word: str, model: str) -> str:
    if model.isupper() and len(model) > 1:
        return word.upper()
    if model.islower():
        return word.lower()
    return word[:1].upper() + word[1:].lower()


def _parse_address(s: str):
    m = _ADDR_RX.match(s or "")
    if not m:
        return None
    via_words = normalize_token(m.group("via").replace(".", " ")).split()
    if not via_words or via_words[0] not in _VIA_CANON:
        return None
    via = _VIA_CANON[via_words[0]]
    if len(via_words) > 1 and via == "avenida":
        via = "avenida " + _VIA_CANON.get(via_words[1], via_words[1])
    comps, pos, rest = [], 0, m.group("rest")
    while True:
        cm = _COMP_RX.match(rest, pos)
        if not cm or cm.end() == pos:
            break
        comps.append(cm)
        pos = cm.end()
    return m, via, comps, rest[pos:]


def _addr_canon(s: str) -> str:
    p = _parse_address(s)
    if not p:
        return " ".join(normalize_token(s).replace("#", " # ").split())
    m, via, comps, tail = p
    letters = "".join(normalize_token(m.group(g) or "") for g in ("let", "bis", "let2", "card"))
    cl = "".join(normalize_token(m.group(g) or "") for g in ("clet", "cbis"))
    cs = " ".join(f"{_COMP_CANON[normalize_token(c.group('kw'))]} {normalize_token(c.group('val'))}" for c in comps)
    return f"{via} {int(m.group('num'))}{letters} # {int(m.group('cross'))}{cl}-{int(m.group('house'))}{normalize_token(m.group('card2') or '')} {cs} {normalize_token(tail)}".strip()


def _comp_value(kw: str, val: str, r: _Rand) -> str:
    letter = val[-1] if val and val[-1].isalpha() and len(val) > 1 else ""
    digits = _only_digits(val)
    if not digits:  # a letter, e.g. "Mz B"
        letters = [c for c in "ABCDEFGH" if c != val.upper()]
        out = r.choice(letters)
        return out.lower() if val.islower() else out
    n = len(digits)
    for _ in range(50):
        if kw in ("apto", "of") and n >= 3:
            floor = r.between(10, 25) if n == 4 else r.between(1, 9)
            cand = f"{floor}{r.between(1, 8):02d}"
        elif kw in ("int", "torre", "bloque", "etapa", "piso") and n <= 2:
            cand = str(r.between(1, 9)) if n == 1 else str(r.between(10, 30))
        else:
            cand = str(r.between(10 ** (n - 1) if n > 1 else 1, 10 ** n - 1))
        if cand != digits:
            break
    if letter:
        cand += r.choice([c for c in "ABCDEF" if c != letter.upper()])
        cand = cand[:-1] + (cand[-1].lower() if letter.islower() else cand[-1])
    return cand


# ---------------------------------------------------------------- dates ---

_MONTHS = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
    "en": ["january", "february", "march", "april", "may", "june", "july", "august", "september",
           "october", "november", "december"],
}
_MONTHS_ABBR = {
    "es": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
    "en": ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
}
_MONTH_LOOKUP: dict[str, tuple[int, str, bool]] = {}
for _lang in ("en", "es"):
    for _i, _w in enumerate(_MONTHS[_lang]):
        _MONTH_LOOKUP[_w] = (_i + 1, _lang, False)
    for _i, _w in enumerate(_MONTHS_ABBR[_lang]):
        _MONTH_LOOKUP.setdefault(_w, (_i + 1, _lang, True))
_MONTH_LOOKUP.update({"setiembre": (9, "es", False), "sept": (9, "es", True), "set": (9, "es", True)})
_MON = r"[A-Za-zÁÉÍÓÚáéíóú]{3,10}"
_DATE_RXS = [
    ("iso", re.compile(r"(?<!\d)(?P<y>\d{4})(?P<s>[-/.])(?P<m>\d{1,2})(?P=s)(?P<d>\d{1,2})(?!\d)")),
    ("num", re.compile(r"(?<!\d)(?P<a>\d{1,2})(?P<s>[-/.])(?P<b>\d{1,2})(?P=s)(?P<y>\d{4}|\d{2})(?!\d)")),
    ("dmy", re.compile(rf"(?<!\d)(?P<d>\d{{1,2}})(?P<o>º|°|st|nd|rd|th)?(?P<s1>\s+de\s+|\s+|-|/)(?P<mon>{_MON})(?P<dot>\.?)"
                       rf"(?P<s2>\s+de\s+|\s+del\s+|,\s*|\s+|-|/)(?P<y>\d{{4}})(?!\d)", re.I)),
    ("mdy", re.compile(rf"(?<![A-Za-z])(?P<mon>{_MON})(?P<dot>\.?)(?P<s1>\s+)(?P<d>\d{{1,2}})(?P<o>st|nd|rd|th)?"
                       rf"(?P<s2>,?\s+de\s+|,\s*|\s+)(?P<y>\d{{4}})(?!\d)", re.I)),
    ("compact", re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})(?P<m>0[1-9]|1[0-2])(?P<d>0[1-9]|[12]\d|3[01])(?!\d)")),
    ("year", re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})(?!\d)")),
]


def _mkdate(y: int, m: int, d: int) -> _dt.date | None:
    try:
        return _dt.date(y, m, d)
    except ValueError:
        return None


def _pad(n: int, model: str) -> str:
    return f"{n:0{len(model)}d}" if len(model) >= 2 else str(n)


def _month_word(month: int, lang: str, abbr: bool, model: str) -> str:
    w = (_MONTHS_ABBR if abbr else _MONTHS)[lang][month - 1]
    return _case_like(w, model)


# ---------------------------------------------------------------- the factory ---

def _name_view(rec: Mapping) -> dict:
    g, s = list(rec["given"]), list(rec["surnames"])
    return {"given": g, "surnames": s, "full": " ".join(g + s), "short": " ".join(g + s[:1]),
            "first": " ".join(g), "gender": rec.get("gender")}


class PseudonymFactory:
    """Deterministic, collision-free pseudonyms per kind.

    secret: HMAC key (keep it stable across runs). blocked_tokens: every given-name and
    surname token of real people (normalized with normalize_token); generated names never
    use one (nor, with fuzzy_block, a token one edit away). state: a dict from a previous
    export_state(). reserved: optional {kind: real values} that must never be generated
    (cedula, phone, email, birth, plate, passport, account, handle, address, name).
    """

    def __init__(self, secret: bytes, blocked_tokens: Iterable[str] = (), state: Mapping | None = None,
                 *, fuzzy_block: bool = True, reserved: Mapping[str, Iterable[str]] | None = None):
        if isinstance(secret, str):
            secret = secret.encode("utf-8")
        if not secret:
            raise ValueError("secret must be a non-empty bytes value")
        self._secret = bytes(secret)
        self._fuzzy = bool(fuzzy_block)
        self._block = _Blocklist()
        self.taken: dict[str, set[str]] = defaultdict(set)
        self.reserved: dict[str, set[str]] = defaultdict(set)
        self._memo: dict[str, dict] = defaultdict(dict)
        self.add_blocked(blocked_tokens or ())
        for kind, values in (reserved or {}).items():
            self.reserve(kind, values)
        if state:
            self.load_state(state)

    # ------------------------------------------------------------ plumbing --
    def _rand(self, kind: str, key: str, *slots) -> _Rand:
        return _Rand(self._secret, ":".join([kind, str(key), *map(str, slots)]))

    def add_blocked(self, tokens: Iterable[str]) -> None:
        for t in tokens:
            if t:
                self._block.add(str(t))

    def is_blocked(self, token: str) -> bool:
        return self._block.hit(token, self._fuzzy)

    @property
    def blocked_tokens(self) -> frozenset[str]:
        return frozenset(self._block.exact)

    def _canon(self, kind: str, value: str) -> str:
        v = str(value or "")
        if kind in ("cedula", "account"):
            return _only_digits(v)
        if kind == "phone":
            d = _only_digits(v)
            return d[-10:] if len(d) >= 10 and d[-10] == "3" else d
        if kind == "email":
            local, domain, _ = _parse_email(v)
            return f"{local}@{domain}" if domain else local
        if kind == "handle":
            return _fold(v).strip()
        if kind in ("plate", "passport"):
            return re.sub(r"[^A-Za-z0-9]", "", v).upper()
        if kind == "birth":
            return self._any_iso(v) or v.strip()
        if kind == "address":
            return _addr_canon(v)
        if kind == "name":
            return normalize_token(v)
        return v.strip()

    def reserve(self, kind: str, values: Iterable[str]) -> None:
        """Real values of a kind that must never come out as a pseudonym. For 'name', the
        tokens are blocked as well."""
        for v in values:
            if not v:
                continue
            c = self._canon(kind, v)
            if c:
                self.reserved[kind].add(c)
            if kind == "name":
                self.add_blocked(str(v).split())

    _DIGIT_KINDS = ("cedula", "phone", "account")

    def _free(self, kind: str, value: str) -> bool:
        if value in self.taken[kind] or value in self.reserved[kind]:
            return False
        # the judge matches digit strings whatever their kind: a pseudonym account must not
        # equal a real cédula or phone either
        if kind in self._DIGIT_KINDS:
            return all(value not in self.reserved[k] for k in self._DIGIT_KINDS)
        return True

    def pool_sizes(self) -> dict[str, int]:
        """Names still usable after blocking (what the >=400/>=400/>=600 targets refer to)."""
        ok = lambda n: not self.is_blocked(n)  # noqa: E731
        return {
            "F": sum(map(ok, F_POOL_COMMON + F_POOL_EXTENDED)),
            "M": sum(map(ok, M_POOL_COMMON + M_POOL_EXTENDED)),
            "surnames": sum(map(ok, SURNAME_POOL)),
        }

    # ------------------------------------------------------------ state --
    def export_state(self) -> dict:
        """JSON-serializable snapshot. It holds real values (blocked tokens, reserved values,
        memo keys): keep it with the pipeline state, never publish it."""
        return {
            "version": STATE_VERSION,
            "blocked": sorted(self._block.exact),
            "taken": {k: sorted(v) for k, v in self.taken.items() if v},
            "reserved": {k: sorted(v) for k, v in self.reserved.items() if v},
            "memo": {k: dict(v) for k, v in self._memo.items() if v},
        }

    def load_state(self, state: Mapping) -> None:
        """Merge a previous export_state(): earlier pseudonyms win and stay taken."""
        if not state:
            return
        self.add_blocked(state.get("blocked") or ())
        for k, vals in (state.get("taken") or {}).items():
            self.taken[k].update(vals)
        for k, vals in (state.get("reserved") or {}).items():
            self.reserved[k].update(vals)
        for k, mem in (state.get("memo") or {}).items():
            self._memo[k].update(mem)
        for rec in self._memo["name"].values():
            self._take_name(rec["given"], rec["surnames"])
        for kind in ("email", "cedula", "phone", "plate", "passport", "account", "handle"):
            self.taken[kind].update(v for v in self._memo[kind].values() if isinstance(v, str))

    # ------------------------------------------------------------ names --
    def _given_ok(self, cand: str, chosen: list[str]) -> bool:
        k = normalize_token(cand)
        return not self.is_blocked(cand) and all(normalize_token(c) != k for c in chosen)

    def _surname_ok(self, cand: str, given: list[str], chosen: list[str]) -> bool:
        k = normalize_token(cand)
        return (not self.is_blocked(cand)
                and all(normalize_token(c) != k for c in chosen + given))

    def _name_keys(self, given: list[str], surnames: list[str]) -> tuple[list[str], str, str]:
        s0 = normalize_token(surnames[0])
        pairs = [f"{normalize_token(g)}|{s0}" for g in given]
        short = normalize_token(" ".join(given + surnames[:1]))
        full = normalize_token(" ".join(given + surnames))
        return pairs, short, full

    def _name_free(self, given: list[str], surnames: list[str]) -> bool:
        # (first given, first surname) must be new, and no middle given name may pair with
        # the surname into someone else's short form: "Ana Milena Pardo" would otherwise
        # contain "Milena Pardo" and that person's records would be over-counted.
        pairs, short, full = self._name_keys(given, surnames)
        famous = f"{normalize_token(' '.join(given))}|{normalize_token(surnames[0])}"
        if pairs[0] in FAMOUS_PAIRS or famous in FAMOUS_PAIRS:
            return False
        first, middle, taken_n = self.taken["name_pair"], self.taken["name_mid_pair"], self.taken["name"]
        if pairs[0] in first or pairs[0] in middle or any(p in first for p in pairs[1:]):
            return False
        if short in taken_n or full in taken_n:
            return False
        return short not in self.reserved["name"] and full not in self.reserved["name"]

    def _take_name(self, given: list[str], surnames: list[str]) -> None:
        pairs, short, full = self._name_keys(given, surnames)
        self.taken["name_pair"].add(pairs[0])
        self.taken["name_mid_pair"].update(pairs[1:])
        self.taken["name"].update((short, full))

    def _draw_name(self, mk: str, gender: str, ng: int, ns: int) -> tuple[list[str], list[str]]:
        rings = _rings()
        for attempt in range(_MAX_ATTEMPTS):
            ga = 0 if attempt < 40 else attempt - 39
            given: list[str] = []
            for j in range(ng):
                r = self._rand("name", mk, f"g{j}", ga)
                seed = r.bits()
                tiers = ("common", "extended") if (j > 0 or r.below(100) < 85) else ("extended", "common")
                pick = None
                for tier in tiers:
                    pick = rings[gender][tier].walk(seed, lambda c: self._given_ok(c, given))
                    if pick:
                        break
                if not pick:
                    raise RuntimeError(f"no {gender} given name left after blocking")
                given.append(pick)
            surnames: list[str] = []
            for j in range(ns):
                r = self._rand("name", mk, f"s{j}", attempt if j == 0 else 0)
                pick = rings["S"].walk(r.bits(), lambda c: self._surname_ok(c, given, surnames))
                if not pick:
                    raise RuntimeError("no surname left after blocking")
                surnames.append(pick)
            if self._name_free(given, surnames):
                return given, surnames
        raise RuntimeError(f"could not find a free name for {mk!r}")

    def name(self, key: str, gender: str | None = None, n_given: int | None = 2, n_surnames: int = 2) -> dict:
        """Colombian full name of the requested gender (random but deterministic when None).

        Returns {"given", "surnames", "full", "short" (given + first surname), "first"
        (given names), "gender"}. The first call for a key decides; later calls with the same
        key return the same name whatever the other arguments. (given name, first surname)
        is unique across all keys, and no token is a blocked (real) token.
        """
        mk = str(key)
        rec = self._memo["name"].get(mk)
        if rec is None:
            g = _coerce_gender(gender) or ("F" if self._rand("name", mk, "gender").below(2) == 0 else "M")
            if n_given is None:
                n_given = 2 if self._rand("name", mk, "n_given").below(100) < 35 else 1
            ng = max(1, min(int(n_given), 3))
            ns = max(1, min(int(n_surnames or 1), 2))
            given, surnames = self._draw_name(mk, g, ng, ns)
            rec = {"given": given, "surnames": surnames, "gender": g}
            self._memo["name"][mk] = rec
            self._take_name(given, surnames)
        return _name_view(rec)

    def _person(self, person_name, key: str) -> tuple[list[str], list[str]]:
        g, s = _split_name(person_name)
        if not g and not s:
            v = self.name(f"~{key}")
            g, s = v["given"], v["surnames"]
        return g, s

    # ------------------------------------------------------------ email / handle --
    def email(self, key: str, original: str, person_name=None, *, original_name=None) -> str:
        """Email built from the pseudonym name, mimicking the original local part
        ('lbermudez' -> 'szambrano', 'paola.quintero' -> 'doris.lozano', digits kept as other
        digits). Corporate/other domains are kept as-is, public providers are re-picked
        among gmail/hotmail/outlook/yahoo/icloud. Spelled-out originals ('x arroba gmail
        punto com') come back spelled out. original_name (real name) sharpens the pattern."""
        local, domain, style = _parse_email(original)
        canon = f"{local}@{domain}" if domain else local
        if canon:
            self.reserved["email"].add(canon)
        mk = f"{key}\x1f{canon}"
        val = self._memo["email"].get(mk)
        if val is None:
            given, surnames = self._person(person_name, key)
            tmpl = _local_template(local, original_name, self._block.exact)
            public = not domain or domain in PUBLIC_EMAIL_DOMAINS
            start = self._rand("email", mk, "provider").below(len(PUBLIC_EMAIL_PROVIDERS))
            for attempt in range(_MAX_ATTEMPTS):
                if public:
                    dom = PUBLIC_EMAIL_PROVIDERS[(start + attempt) % len(PUBLIC_EMAIL_PROVIDERS)]
                    variant = attempt // len(PUBLIC_EMAIL_PROVIDERS)
                else:
                    dom, variant = domain, attempt
                loc = _render_local(tmpl, given, surnames, self._rand("email", mk, "local", variant), variant)
                if not loc:
                    loc = _alnum(given[0] if given else "x")[:1] + _alnum(surnames[0] if surnames else "user")
                cand = f"{loc}@{dom}"
                if cand != canon and self._free("email", cand):
                    val = cand
                    break
            else:
                raise RuntimeError(f"could not find a free email for {mk!r}")
            self._memo["email"][mk] = val
            self.taken["email"].add(val)
        return _style_email(val, style)

    def handle(self, key: str, original: str, person_name=None, *, original_name=None) -> str:
        """Slack-style handle mirroring the original pattern ('andres.villamil' -> 'hugo.cano',
        'mquiroga' -> 'hcano'), unique across keys."""
        canon = _fold(original).strip()
        if canon:
            self.reserved["handle"].add(canon)
        mk = f"{key}\x1f{canon}"
        val = self._memo["handle"].get(mk)
        if val is None:
            given, surnames = self._person(person_name, key)
            tmpl = _local_template(canon, original_name, self._block.exact)
            for attempt in range(_MAX_ATTEMPTS):
                loc = _render_local(tmpl, given, surnames, self._rand("handle", mk, attempt), attempt)
                if loc and loc != canon and self._free("handle", loc):
                    val = loc
                    break
            else:
                raise RuntimeError(f"could not find a free handle for {mk!r}")
            self._memo["handle"][mk] = val
            self.taken["handle"].add(val)
        return val

    # ------------------------------------------------------------ numbers --
    def cedula(self, key: str, original: str) -> str:
        """Same digit count, first two digits kept (issuing series), every other digit
        changed; formatting of the original kept ('1.093.418.276' -> '1.093.552.810')."""
        digits = _only_digits(original)
        if not digits:
            return original
        self.reserved["cedula"].add(digits)
        mk = f"{key}\x1f{digits}"
        val = self._memo["cedula"].get(mk)
        if val is None:
            n = len(digits)
            keep = 2 if n >= 6 else (1 if n >= 3 else 0)
            for attempt in range(_MAX_ATTEMPTS):
                r = self._rand("cedula", mk, attempt)
                out = list(digits[:keep])
                for i in range(keep, n):
                    pool = "012345" if (n == 10 and i == 2 and digits[:2] == "11") else ("123456789" if i == 0 else _DIGITS)
                    out.append(r.choice([d for d in pool if d != digits[i]] or [d for d in _DIGITS if d != digits[i]]))
                cand = "".join(out)
                if cand != digits and self._free("cedula", cand):
                    val = cand
                    break
            else:
                raise RuntimeError(f"could not find a free cedula for {mk!r}")
            self._memo["cedula"][mk] = val
            self.taken["cedula"].add(val)
        return format_like(original, val)

    def phone(self, key: str, original: str) -> str:
        """Colombian mobile (3xx operator prefix 300-324/350-351, different from the
        original's) with every subscriber digit changed; '+57', spaces and dashes kept.
        Landlines keep their area prefix and change the rest."""
        digits = _only_digits(original)
        if not digits:
            return original
        mobile = len(digits) >= 10 and digits[-10] == "3"
        national, prefix = (digits[-10:], digits[:-10]) if mobile else (digits, "")
        self.reserved["phone"].add(national)
        mk = f"{key}\x1f{national}"
        val = self._memo["phone"].get(mk)
        if val is None:
            for attempt in range(_MAX_ATTEMPTS):
                r = self._rand("phone", mk, attempt)
                if mobile:
                    op = r.choice([p for p in MOBILE_PREFIXES if p != national[:3]])
                    cand = op + "".join(r.choice([d for d in _DIGITS if d != national[i]]) for i in range(3, 10))
                else:
                    keep = 3 if (len(national) == 10 and national.startswith("60")) else (1 if len(national) > 1 else 0)
                    cand = national[:keep] + "".join(
                        r.choice([d for d in _DIGITS if d != national[i]]) for i in range(keep, len(national)))
                if cand != national and self._free("phone", cand):
                    val = cand
                    break
            else:
                raise RuntimeError(f"could not find a free phone for {mk!r}")
            self._memo["phone"][mk] = val
            self.taken["phone"].add(val)
        return format_like(original, prefix + val)

    def account(self, key: str, original: str) -> str:
        """Same digit count and separators, first digit kept, the rest changed; 13-19 digit
        numbers starting with 3/4/5/6 (cards) come out Luhn-valid. Masks such as '****' stay."""
        digits = _only_digits(original)
        if not digits:
            return original
        self.reserved["account"].add(digits)
        mk = f"{key}\x1f{digits}"
        val = self._memo["account"].get(mk)
        if val is None:
            n = len(digits)
            masked = bool(re.search(r"[*xX•]", original or ""))
            card = 13 <= n <= 19 and digits[0] in "3456" and not masked
            for attempt in range(_MAX_ATTEMPTS):
                r = self._rand("account", mk, attempt)
                keep = 1 if n > 1 else 0
                out = digits[:keep] + "".join(r.choice([d for d in _DIGITS if d != digits[i]]) for i in range(keep, n))
                if card:
                    out = out[:-1] + _luhn_digit(out[:-1])
                if out != digits and self._free("account", out):
                    val = out
                    break
            else:
                raise RuntimeError(f"could not find a free account for {mk!r}")
            self._memo["account"][mk] = val
            self.taken["account"].add(val)
        return format_like(original, val)

    def _alnum_kind(self, kind: str, key: str, original: str, keep_first_letter: bool) -> str:
        canon = re.sub(r"[^A-Za-z0-9]", "", original or "").upper()
        if not canon:
            return original
        self.reserved[kind].add(canon)
        mk = f"{key}\x1f{canon}"
        val = self._memo[kind].get(mk)
        if val is None:
            for attempt in range(_MAX_ATTEMPTS):
                r = self._rand(kind, mk, attempt)
                out = []
                for i, ch in enumerate(canon):
                    if keep_first_letter and i == 0 and ch.isalpha():
                        out.append(ch)
                    elif ch.isdigit():
                        out.append(r.choice([d for d in _DIGITS if d != ch]))
                    else:
                        out.append(r.choice([c for c in _PLATE_LETTERS if c != ch]))
                cand = "".join(out)
                letters = "".join(c for c in cand if c.isalpha())
                if cand != canon and letters[:3] not in _PLATE_STOP and self._free(kind, cand):
                    val = cand
                    break
            else:
                raise RuntimeError(f"could not find a free {kind} for {mk!r}")
            self._memo[kind][mk] = val
            self.taken[kind].add(val)
        return _alnum_like(original, val)

    def plate(self, key: str, original: str) -> str:
        """Same pattern (ABC123 car, ABC12D motorcycle), every letter and digit changed,
        separator and case kept ('MQT-582' -> 'KRB-264')."""
        return self._alnum_kind("plate", key, original, keep_first_letter=False)

    def passport(self, key: str, original: str) -> str:
        """Same shape (letters and digits at the same positions), series letter kept,
        everything else changed ('AE903614' -> 'AK180497')."""
        return self._alnum_kind("passport", key, original, keep_first_letter=True)

    # ------------------------------------------------------------ address --
    def address(self, key: str, original: str) -> str:
        """Plausible Colombian urban address in the style of the original (abbreviated or
        full via words, '#' or 'No.', complements such as 'apto'/'of'/'casa'/'torre' kept as
        keywords with new numbers); via number, cross street and house number all change."""
        canon = _addr_canon(original)
        self.reserved["address"].add(canon)
        mk = f"{key}\x1f{canon}"
        rec = self._memo["address"].get(mk)
        parsed = _parse_address(original)
        if rec is None:
            for attempt in range(_MAX_ATTEMPTS):
                r = self._rand("address", mk, attempt)
                rec = self._gen_address(parsed, r)
                cand = _addr_canon(self._render_address(original, parsed, rec))
                if cand != canon and self._free("address", cand):
                    break
            else:
                raise RuntimeError(f"could not find a free address for {mk!r}")
            self._memo["address"][mk] = rec
            self.taken["address"].add(cand)
        return self._render_address(original, parsed, rec)

    @staticmethod
    def _gen_address(parsed, r: _Rand) -> dict:
        via = r.choice(_VIA_TYPES)
        o_num = o_cross = o_house = -1
        comps: list[str] = []
        if parsed:
            m, _, cms, _ = parsed
            o_num, o_cross, o_house = int(m.group("num")), int(m.group("cross")), int(m.group("house"))
            comps = [_comp_value(_COMP_CANON[normalize_token(c.group("kw"))], c.group("val"), r) for c in cms]
        num = r.between(1, 150 if via == "avenida" else 170)
        while num == o_num:
            num = r.between(1, 170)
        cross = r.between(1, 130)
        while cross == o_cross:
            cross = r.between(1, 130)
        house = r.between(1, 99)
        while house == o_house:
            house = r.between(1, 99)
        return {
            "via": via, "num": num, "let": r.choice("ABCDEFGH") if r.chance(0.3) else "",
            "bis": r.chance(0.12), "sur": via != "avenida" and r.chance(0.1),
            "cross": cross, "clet": r.choice("ABCDEF") if r.chance(0.15) else "", "house": house,
            "comps": comps,
        }

    @staticmethod
    def _render_address(original: str, parsed, rec: dict) -> str:
        if not parsed:
            via = _VIA_FULL[rec["via"]]
            let = rec["let"]
            core = f"{via} {rec['num']}{let}{' Bis' if rec['bis'] else ''}{' Sur' if rec['sur'] else ''}"
            return f"{core} # {rec['cross']}{rec['clet']}-{rec['house']}"
        m, o_via, cms, tail = parsed
        via_tok = m.group("via").split()[0]
        model = via_tok.rstrip(".")
        if rec["via"] == o_via:
            via_out = m.group("via")
        else:
            abbr = normalize_token(model) not in _VIA_FULL_WORDS
            if abbr:
                word = _VIA_ABBR[rec["via"]]
                if rec["via"] == "carrera" and normalize_token(model) in ("kr", "kra"):
                    word = "Kr"
                if rec["via"] == "calle" and normalize_token(model) in ("cll", "clle"):
                    word = "Cll"
                word += "." if via_tok.endswith(".") else ""
            else:
                word = _VIA_FULL[rec["via"]]
            via_out = _case_like(word, model)
        lower = model.islower()
        bis = " bis" if lower else " Bis"
        sur = " sur" if lower else " Sur"
        let = rec["let"].lower() if lower else rec["let"]
        clet = rec["clet"].lower() if lower else rec["clet"]
        house = str(rec["house"])
        if m.group("house").startswith("0") and len(m.group("house")) == 2:
            house = f"{rec['house']:02d}"
        out = (f"{m.group('lead')}{via_out}{m.group('s1')}{rec['num']}{let}{bis if rec['bis'] else ''}"
               f"{sur if rec['sur'] else ''}{m.group('sep')}{rec['cross']}{clet}{m.group('dash')}{house}")
        for cm, val in zip(cms, rec["comps"]):
            out += f"{cm.group('pre')}{cm.group('kw')}{cm.group('dot')}{cm.group('mid')}{val}"
        return out + tail

    # ------------------------------------------------------------ birth dates --
    def _shift_iso(self, key: str, iso: str) -> str:
        mk = f"{key}\x1f{iso}"
        val = self._memo["birth"].get(mk)
        if val is None:
            d = _dt.date.fromisoformat(iso)
            limit = max(MAX_BIRTH, d)
            r = self._rand("birth", mk, 0)
            for _ in range(_MAX_ATTEMPTS):
                days = r.between(200, 1500)
                sign = 1 if r.below(2) == 0 else -1
                nd = None
                for s in (sign, -sign):
                    try:
                        c = d + _dt.timedelta(days=s * days)
                    except OverflowError:
                        continue
                    if 1900 <= c.year and c <= limit:
                        nd = c
                        break
                if nd is not None and nd.isoformat() not in self.reserved["birth"]:
                    val = nd.isoformat()
                    break
            else:
                val = (d - _dt.timedelta(days=1099)).isoformat()
            self._memo["birth"][mk] = val
        return val

    def _any_iso(self, s: str) -> str | None:
        for kind, rx in _DATE_RXS[:-1]:
            m = rx.search(s or "")
            if not m:
                continue
            d = self._match_date(kind, m, None, None)
            if d:
                return d[0].isoformat()
        return None

    def _match_date(self, kind, m, key, dayfirst):
        if kind in ("iso", "compact"):
            d = _mkdate(int(m.group("y")), int(m.group("m")), int(m.group("d")))
            return (d, None) if d else None
        if kind == "num":
            a, b, y = int(m.group("a")), int(m.group("b")), m.group("y")
            year = int(y) if len(y) == 4 else (1900 + int(y) if int(y) >= 30 else 2000 + int(y))
            dmy, mdy = _mkdate(year, b, a), _mkdate(year, a, b)
            if dmy and mdy and a != b:
                if dayfirst is None and key is not None:
                    has = lambda dd: f"{key}\x1f{dd.isoformat()}" in self._memo["birth"]  # noqa: E731
                    dayfirst = not (has(mdy) and not has(dmy))
                return (dmy, "dmy") if dayfirst is not False else (mdy, "mdy")
            if dmy:
                return dmy, "dmy"
            return (mdy, "mdy") if mdy else None
        mon = _MONTH_LOOKUP.get(normalize_token(m.group("mon")))
        if not mon:
            return None
        d = _mkdate(int(m.group("y")), mon[0], int(m.group("d")))
        return (d, mon) if d else None

    def birth(self, key: str, original: str, dayfirst: bool | None = None) -> str:
        """Shift a date by a deterministic 200-1500 days (either direction, never past an
        adult's latest birth date, never onto a reserved real date) and write it back in the
        original's format: ISO, dd/mm/yyyy (or mm/dd/yyyy when that is the only valid
        reading, or when dayfirst=False), '23 de julio de 1997', 'July 23, 1997', compact
        yyyymmdd, or a bare year. Text around the date is kept."""
        s = original or ""
        iso = self._any_iso(s)
        if iso:
            self.reserved["birth"].add(iso)
        for kind, rx in _DATE_RXS:
            m = rx.search(s)
            if not m:
                continue
            if kind == "year":
                return s[:m.start()] + self._shift_year(key, m.group("y")) + s[m.end():]
            got = self._match_date(kind, m, key, dayfirst)
            if not got:
                continue
            d, extra = got
            nd = _dt.date.fromisoformat(self._shift_iso(key, d.isoformat()))
            if kind == "iso":
                rep = f"{nd.year:04d}{m.group('s')}{_pad(nd.month, m.group('m'))}{m.group('s')}{_pad(nd.day, m.group('d'))}"
            elif kind == "compact":
                rep = f"{nd.year:04d}{nd.month:02d}{nd.day:02d}"
            elif kind == "num":
                y = f"{nd.year:04d}" if len(m.group("y")) == 4 else f"{nd.year % 100:02d}"
                first, second = (nd.day, nd.month) if extra == "dmy" else (nd.month, nd.day)
                a, b = m.group("a"), m.group("b")
                padded = a.startswith("0") or b.startswith("0") or (len(a) == 2 and len(b) == 2)
                fmt = (lambda v: f"{v:02d}") if padded else str
                rep = f"{fmt(first)}{m.group('s')}{fmt(second)}{m.group('s')}{y}"
            else:
                month, lang, abbr = extra
                word = _month_word(nd.month, lang, abbr, m.group("mon"))
                day = f"{nd.day:02d}" if m.group("d").startswith("0") else str(nd.day)
                o = m.group("o") or ""
                if o in ("st", "nd", "rd", "th"):
                    o = {1: "st", 2: "nd", 3: "rd"}.get(nd.day if nd.day < 20 else nd.day % 10, "th")
                if kind == "dmy":
                    rep = f"{day}{o}{m.group('s1')}{word}{m.group('dot')}{m.group('s2')}{nd.year}"
                else:
                    rep = f"{word}{m.group('dot')}{m.group('s1')}{day}{o}{m.group('s2')}{nd.year}"
            return s[:m.start()] + rep + s[m.end():]
        return s

    def _shift_year(self, key: str, year: str) -> str:
        prefix = f"{key}\x1f{year}-"
        for mk, v in self._memo["birth"].items():
            if mk.startswith(prefix):
                return v[:4]
        mk = f"{key}\x1f{year}"
        val = self._memo["birth_year"].get(mk)
        if val is None:
            r = self._rand("birth_year", mk, 0)
            y, off = int(year), r.between(1, 4) * (1 if r.below(2) == 0 else -1)
            top = max(MAX_BIRTH.year, y)
            val = str(next((c for c in (y + off, y - off) if 1900 <= c <= top), y - abs(off)))
            self._memo["birth_year"][mk] = val
        return val

    # ------------------------------------------------------------ places --
    def pseudo_barrio(self, key: str, city: str, original_barrio: str) -> str:
        """pseudo_barrio() keyed with this factory's secret."""
        return pseudo_barrio(key, city, original_barrio, self._secret)
