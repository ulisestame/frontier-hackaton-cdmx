"""Repair step of the self-check: replace declared originals still present in the output.

The batch self-check (pipeline.build_entities) looks for every declared original of every person
in the whole output with the validator's matching (textnorm.contains). Before this step a hit was
undeclared and reported. Now each hit is first located in the exact characters of the field it
came from and replaced by that person's pseudonym of the same kind, rendered in the matched style;
the output is checked again (at most PASSES times). Only what is still present afterwards falls to
the old last resort (undeclare + report).

A span is never touched when it overlaps a kept term or another person's pseudonym, when the
original belongs to more than one person, or when the character-level mapping does not reproduce
the validator's normalization exactly; those cases stay with the last resort.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Any

from .. import fakes
from .engine import KEPT_TERMS, Engine, Person, canon, split_name
from .textnorm import (
    _RX_BLANKS,
    _RX_TEXT,
    _SPACE_CHARS,
    CONFUSABLES,
    Prepared,
    compact_digits,
    contains,
    is_bare_name,
    norm,
    only_digits,
    record_text,
)

PASSES = 2
ID_KINDS = ("email", "cedula", "phone", "account", "birth", "plate", "passport", "handle", "address")
_DIGIT_SEPS = set(f"{_SPACE_CHARS}.,'’`\xb4\xb7/-–—_")


# ------------------------------------------------------------ span location ---

def _clean_chars(raw: str):
    """(char, raw_index) pairs of textnorm.clean(raw), built one raw character at a time."""
    for i, ch in enumerate(raw):
        for c in unicodedata.normalize("NFKC", ch):
            c = CONFUSABLES.get(c, c)
            cat = unicodedata.category(c)
            if cat == "Cf":
                continue
            yield (" " if cat == "Zs" or c in "\t\r\n\v\f" else c), i


def _collapse(pairs) -> tuple[list[str], list[int]]:
    chars: list[str] = []
    index: list[int] = []
    for c, i in pairs:
        if c == " " and chars and chars[-1] == " ":
            continue  # clean() collapses runs of spaces
        chars.append(c)
        index.append(i)
    return chars, index


def mapped_norm(raw: str) -> tuple[str, list[int]] | None:
    """textnorm.norm(raw) plus, for each normalized char, the raw index it came from."""
    chars, index = _collapse(_clean_chars(raw))
    out: list[str] = []
    out_index: list[int] = []
    for c, i in zip(chars, index, strict=True):
        for d in unicodedata.normalize("NFD", c):
            if unicodedata.category(d) == "Mn":
                continue
            for e in d.lower().replace("ß", "ss"):
                out.append(e)
                out_index.append(i)
    normed = "".join(out)
    return (normed, out_index) if normed == norm(raw) else None


def mapped_compact(raw: str) -> tuple[str, list[int]] | None:
    """textnorm.compact_digits(raw) plus the raw index of each kept char."""
    chars, index = _collapse(_clean_chars(raw))
    keep = [k for k in range(len(chars))
            if not (chars[k] in _DIGIT_SEPS and 0 < k < len(chars) - 1
                    and re.match(r"\d", chars[k - 1]) and re.match(r"\d", chars[k + 1]))]
    compact = "".join(chars[k] for k in keep)
    return (compact, [index[k] for k in keep]) if compact == compact_digits(raw) else None


class Field:
    """A field's text with its mapped normalized and digit-compacted forms, computed once."""

    def __init__(self, raw: str):
        self.raw = raw
        self._norm: tuple[str, list[int]] | None | bool = False
        self._compact: tuple[str, list[int]] | None | bool = False

    @property
    def norm(self):
        if self._norm is False:
            self._norm = mapped_norm(self.raw)
        return self._norm

    @property
    def compact(self):
        if self._compact is False:
            self._compact = mapped_compact(self.raw)
        return self._compact


def _is_digit_needle(needle: str) -> bool:
    digits = only_digits(needle)
    return bool(digits) and len(digits) >= 6 and len(digits) >= 0.6 * len(needle) and not re.search(r"[a-zA-Z]", needle)


def locate(raw: str | Field, needle: str) -> list[tuple[int, int]]:
    """Raw-character spans of `needle` in `raw`, under the same rules as textnorm.contains."""
    field = raw if isinstance(raw, Field) else Field(raw)
    if not needle or not field.raw:
        return []
    digits = only_digits(needle)
    if _is_digit_needle(needle):
        mapped = field.compact
        if mapped is None:
            return []
        compact, index = mapped
        candidates = {digits} | ({digits[2:]} if len(digits) == 12 and digits.startswith("57") else set())
        spans = []
        for d in candidates:
            for m in re.finditer(rf"(?<!\d)(?:57)?({re.escape(d)})(?!\d)", compact):
                spans.append((index[m.start(1)], index[m.end(1) - 1] + 1))
        return sorted(set(spans))
    mapped = field.norm
    if mapped is None:
        return []
    normed, index = mapped
    n = norm(needle)
    if _RX_TEXT.match(n) and re.search(r"[a-z]", n):
        found = list(re.finditer(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])", normed))
        if not found:
            words = [w for w in _RX_BLANKS.split(n) if w]
            if len(words) >= 2 and all(len(w) >= 3 for w in words):
                pattern = rf"[{_SPACE_CHARS}]*".join(re.escape(w) for w in words)
                found = list(re.finditer(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", normed))
        return [(index[m.start()], index[m.end() - 1] + 1) for m in found if m.end() > m.start()]
    spans, start = [], normed.find(n)
    while start >= 0 and n:
        spans.append((index[start], index[start + len(n) - 1] + 1))
        start = normed.find(n, start + 1)
    return spans


# ---------------------------------------------------------------- rendering ---

def original_kind(p: Person, original: str) -> str | None:
    """Kind of a declared original, from the person's own ids; None when it cannot be told."""
    for kind in ID_KINDS:
        if canon(kind, original) in p.ids.get(kind, ()):
            return kind
    if "@" in original:
        return "email"
    if _is_digit_needle(original) or any(c.isdigit() for c in original):
        return None  # a number we cannot attribute to a kind: leave it to the last resort
    return "name"


def render(eng: Engine, p: Person, kind: str, original: str, surface: str) -> str:
    """The person's pseudonym of `kind`, in the style of the matched `surface`."""
    if kind == "name":
        words = [w for w in re.split(r"[\s_\-]+", original) if w]
        given, surnames = split_name(" ".join(words))
        out = eng.render_name(p, max(1, len(given)), len(surnames), surface, surface, 0, len(surface))
        if len(words) > 1 and " " in out and not re.search(r"[\s_\-]", surface):
            out = out.replace(" ", "")  # a glued form stays glued
        return out
    if kind == "birth":
        key = f"{p.pid}:{canon('birth', original)}"
        return eng.f.birth(key, surface) if surface != original else eng.pseudo("birth", p, original)
    if kind in ("cedula", "phone", "account"):
        return fakes.format_like(surface, eng.pseudo(kind, p, original))
    value = eng.pseudo(kind, p, original)
    return value.upper() if surface.isupper() and kind in ("email", "handle") else value


# ------------------------------------------------------------------- repair ---

def _strings(value: Any, path: tuple = ()):
    """(path, text) of every string value of a record, keys excluded (they are not data)."""
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _strings(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _strings(v, path + (i,))


def _set(record: dict, path: tuple, text: str) -> None:
    target = record
    for step in path[:-1]:
        target = target[step]
    target[path[-1]] = text


def _overlaps(span: tuple[int, int], others: list[tuple[int, int]]) -> bool:
    return any(span[0] < e and s < span[1] for s, e in others)


PSEUDO_KINDS = ("email", "phone", "cedula", "address", "birth_iso", "plate", "passport", "account", "handle")


def _declared(eng: Engine, hay: Any, p: Person) -> bool:
    """build_entities lists a person only when one of their pseudonyms is in their records."""
    recs = sorted(p.records)
    names = ([eng.pname(p)["short"]] + sorted(p.rendered.get("name", set()), key=len, reverse=True)) if p.given else []
    if any(hay.in_records(recs, c) for c in names):
        return True
    return any(hay.in_records(recs, c) for kind in PSEUDO_KINDS for c in p.rendered.get(kind, ()))


def declared_candidates(eng: Engine, hay: Any) -> list[tuple[Person, str]]:
    """The (person, original) pairs build_entities would declare, with its own filters."""
    kept_originals = [t for t in eng.kept_seen if len(t) >= 4]
    out = []
    for pid in sorted(eng.persons):
        p = eng.persons[pid]
        if not p.records or not _declared(eng, hay, p):
            continue
        for o in sorted(p.originals):
            if len(o) >= 3 and not is_bare_name(o) and not any(contains(k, o) for k in kept_originals):
                out.append((p, o))
    return out


def repair_leaks(eng: Engine, records: list[dict], hay_factory) -> tuple[Counter, Any]:
    """Replace leaked declared originals in `records` (in place). Returns (repaired by kind, haystack).

    `hay_factory(records)` builds the pipeline's Haystack; the last one is returned so the
    caller can reuse its answers when nothing changed.
    """
    repaired: Counter = Counter()
    hay = hay_factory(records)
    candidates = declared_candidates(eng, hay)
    owners: dict[str, set[str]] = {}
    for p, o in candidates:
        owners.setdefault(norm(o), set()).add(p.pid)
    pending = candidates
    by_id = {r["id"]: r for r in records}
    for _ in range(PASSES):
        leaks = [(p, o) for p, o in pending if hay.has(o)]
        if not leaks:
            break
        protected = [t for t in set(KEPT_TERMS) | set(eng.kept_seen) if t]
        changed: set[str] = set()
        # per record and field: candidate replacements, applied right to left
        plans: dict[tuple[str, tuple], list[tuple[int, int, str, str]]] = {}
        texts: dict[tuple[str, tuple], str] = {}
        for p, o in leaks:
            kind = original_kind(p, o)
            if kind is None or len(owners.get(norm(o), ())) != 1:
                continue  # unknown kind, or an original shared by two people: the last resort decides
            others = [v for q in eng.persons.values() if q.pid != p.pid
                      for vals in q.rendered.values() for v in vals if v]
            for rid, prepared in hay.by_id.items():
                if not contains(prepared, o):
                    continue
                for path, text in _strings({k: v for k, v in by_id[rid].items() if k != "id"}):
                    field = Field(text)
                    spans = locate(field, o)
                    if not spans:
                        continue
                    normed = field.norm[0] if field.norm else norm(text)
                    blocked = [s for t in protected if norm(t) in normed for s in locate(field, t)]
                    blocked += [s for v in others if norm(v) in normed for s in locate(field, v)]
                    for s, e in spans:
                        if _overlaps((s, e), blocked):
                            continue
                        texts[(rid, path)] = text
                        plans.setdefault((rid, path), []).append((s, e, render(eng, p, kind, o, text[s:e]), kind))
        for (rid, path), items in plans.items():
            text = texts[(rid, path)]
            chosen: list[tuple[int, int, str, str]] = []
            for item in sorted(items, key=lambda x: (-(x[1] - x[0]), x[0])):  # longest span first
                if not _overlaps(item[:2], [(c[0], c[1]) for c in chosen]):
                    chosen.append(item)
            for s, e, replacement, kind in sorted(chosen, reverse=True):
                text = text[:s] + replacement + text[e:]
                repaired[kind] += 1
            _set(by_id[rid], path, text)
            changed.add(rid)
        if not changed:
            break
        hay = hay_factory(records)
        pending = leaks
    return repaired, hay


__all__ = ["PASSES", "Field", "declared_candidates", "locate", "mapped_compact", "mapped_norm", "original_kind",
           "render", "repair_leaks", "Prepared", "record_text"]
