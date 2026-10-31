"""Text matching that mirrors the official validator (material-reto/validar.mjs).

We use the same normalization and containment rules the judge uses, so our own
leak check before publishing gives the same verdict the evaluator will.
"""

import re
import unicodedata

CONFUSABLES = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c",
    "х": "x", "у": "y", "і": "i", "ј": "j", "ѕ": "s",
    "А": "A", "Е": "E", "О": "O", "Р": "P", "С": "C",
    "Х": "X", "У": "Y", "І": "I", "Ј": "J", "Ѕ": "S",
    "В": "B", "Н": "H", "К": "K", "М": "M", "Т": "T",
    "ο": "o", "α": "a", "ρ": "p", "ν": "v", "ι": "i",
    "ℓ": "l", "ı": "i", "ɑ": "a",
}
_SPACE_CHARS = "\t\n\v\f\r \x1c-\x1f\x85\xa0  -     　"
_RX_DIGIT_SEP = re.compile(rf"(?<=\d)[{_SPACE_CHARS}.,'’`\xb4\xb7/\-–—_](?=\d)")
_RX_SPACES = re.compile(r" {2,}")
_RX_TEXT = re.compile(r"^[\w .'_-]+$")
_RX_BLANKS = re.compile(rf"[{_SPACE_CHARS}]+")


def clean(s: str) -> str:
    base = unicodedata.normalize("NFKC", s)
    out = []
    for c in base:
        c = CONFUSABLES.get(c, c)
        cat = unicodedata.category(c)
        if cat == "Cf":
            continue
        if cat == "Zs" or c in "\t\r\n\v\f":
            out.append(" ")
        else:
            out.append(c)
    return _RX_SPACES.sub(" ", "".join(out))


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """casefold + no accents + NFKC + confusables, like the judge's norm()."""
    return strip_accents(clean(s)).lower().replace("ß", "ss")


def compact_digits(s: str) -> str:
    return _RX_DIGIT_SEP.sub("", clean(s))


def only_digits(s: str) -> str:
    return "".join(c for c in s if c.isdigit())


class Prepared:
    """A haystack whose normalized and digit-compacted forms are computed once.

    contains() accepts it in place of a str and returns exactly the same answer; the
    entity self-check asks thousands of questions of the same multi-megabyte output.
    """

    __slots__ = ("raw", "_normed", "_compact")

    def __init__(self, raw: str):
        self.raw = raw
        self._normed: str | None = None
        self._compact: str | None = None

    @property
    def normed(self) -> str:
        if self._normed is None:
            self._normed = norm(self.raw)
        return self._normed

    @property
    def compact(self) -> str:
        if self._compact is None:
            self._compact = compact_digits(self.raw)
        return self._compact


def _digits_in(haystack: "str | Prepared", digits: str) -> bool:
    compact = haystack.compact if isinstance(haystack, Prepared) else compact_digits(haystack)
    candidates = {digits}
    if len(digits) == 12 and digits.startswith("57"):
        candidates.add(digits[2:])
    return any(re.search(rf"(?<!\d)(?:57)?{re.escape(d)}(?!\d)", compact) for d in candidates)


def contains(haystack: "str | Prepared", needle: str) -> bool:
    """Port of contiene(): does the judge consider `needle` present in `haystack`?"""
    if not needle:
        return False
    digits = only_digits(needle)
    if digits and len(digits) >= 6 and len(digits) >= 0.6 * len(needle) and not re.search(r"[a-zA-Z]", needle):
        return _digits_in(haystack, digits)
    h = haystack.normed if isinstance(haystack, Prepared) else norm(haystack)
    n = norm(needle)
    if _RX_TEXT.match(n) and re.search(r"[a-z]", n):
        if re.search(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", h):
            return True
        words = [w for w in _RX_BLANKS.split(n) if w]
        if len(words) >= 2 and all(len(w) >= 3 for w in words):
            pattern = rf"[{_SPACE_CHARS}]*".join(re.escape(w) for w in words)
            return re.search(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", h) is not None
        return False
    return n in h


def is_bare_name(s: str) -> bool:
    """Port of esNombreSuelto(): a single capitalized word the judge does not sweep."""
    if not s or " " in s or "@" in s or any(c.isdigit() for c in s):
        return False
    first = s[0]
    return first.upper() == first and first.lower() != first


def flatten(value) -> list[str]:
    """Port of plano(): keys and values of a record, as the judge reads them."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, bool):
        return ["True" if value else "False"]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list):
        return [x for v in value for x in flatten(v)]
    if isinstance(value, dict):
        out: list[str] = []
        for k, v in value.items():
            out.append(k)
            out.extend(flatten(v))
        return out
    return [str(value)]


def record_text(rec: dict) -> str:
    return " | ".join(flatten({k: v for k, v in rec.items() if k != "id"}))
