"""Anonymization engine: who is who, what to replace, and how to render it.

Order of trust (cheapest and most reliable first):
1. Structured sources (clientes, empleados, chat profiles) build the identity registry.
2. Deterministic detectors find identifiers and known name forms in free text.
3. A narrow heuristic catches unknown full names (given-name lexicon + capitalized surname).
Everything unknown that looks personal is replaced (fail-closed), never left raw.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from .. import fakes
from .textnorm import norm, only_digits, strip_accents

# ---------------------------------------------------------------- lexicons ---

PARTICLE_START = {"de", "del"}
PARTICLE_MID = {"la", "las", "los"}

# Organizations, brands, places and public figures that must be kept as-is.
KEPT_TERMS = [
    "Bancolombia", "Banco de Bogotá", "Banco de Occidente", "Banco Popular", "Banco Agrario",
    "Banco Caja Social", "Davivienda", "BBVA", "Scotiabank", "Colpatria", "Itaú", "Santander",
    "Nequi", "Daviplata", "PSE", "Efecty", "Baloto", "Movii", "Lulo Bank", "Nu", "Rappi", "RappiPay",
    "Carulla", "Éxito", "Olímpica", "Falabella", "Alkosto", "Jumbo", "Homecenter", "Ara", "D1",
    "Nutresa", "Unicentro", "Andino", "Santafé", "Oviedo", "El Tesoro", "Juan Valdez", "Avianca",
    "Claro", "Movistar", "Tigo", "WOM", "WhatsApp", "Google", "Apple", "Visa", "Mastercard",
    "American Express", "Superfinanciera", "Superintendencia Financiera", "SIC",
    "Superintendencia de Industria y Comercio", "DIAN", "Datacrédito", "TransUnion", "Cifin",
    "Registraduría", "Policía Nacional", "Fiscalía", "Kipu Pay", "Kipi", "Plaza Botero",
    "Shakira", "Fernando Botero", "Gabriel García Márquez", "Gustavo Petro", "Álvaro Uribe",
    "Iván Duque", "James Rodríguez", "Karol G", "Maluma", "J Balvin", "Egan Bernal",
    "Nairo Quintana", "Mariana Pajón", "Simón Bolívar", "Antonio Nariño", "Rafael Uribe Uribe",
    "Francisco de Paula Santander", "Veloz",
]
_KEPT_NORM = {norm(t) for t in KEPT_TERMS}

ROLE_MAILBOXES = {"soporte", "support", "info", "contacto", "ventas", "notificaciones", "noreply",
                  "no-reply", "pagos", "cobranza", "cobros", "fraude", "seguridad", "talento",
                  "rrhh", "legal", "juridica", "facturacion", "admin", "hola", "ayuda", "pqrs"}

NAME_CUE = re.compile(
    r"(?i)(?:\b(?:hola|buen[oa]s(?: d[ií]as| tardes| noches)?|hi|hello|hey|soy|me llamo|mi nombre es|"
    r"habla|gracias|thanks|thank you|con|para|a|de|y|e|señor|señora|sr|sra|srta|don|doña|dr|dra|"
    r"ingeniera|ingeniero|cliente|clienta|agente|compañera|compañero|hermana|hermano|mamá|papá|"
    r"esposa|esposo|hija|hijo|tía|tío|prima|primo|familiar|titular|firmad[oa] por|preparad[oa] por|"
    r"elaborad[oa] por|revisad[oa] por|aprobad[oa] por|atendid[oa] por|dear|estimad[oa]|querid[oa])"
    r"[\s,.:;!¡¿?]*)$"
)
OCC_CUE = re.compile(
    r"(?i)\b(?:yo\s+)?(?:soy|trabajo\s+como|trabajo\s+de|me\s+desempeño\s+como|de\s+profesión|"
    r"mi\s+profesión\s+es|i\s+am\s+an?|i'm\s+an?|work\s+as\s+an?)\s+(?:un|una|el|la)?\s*$"
)
YEAR_RX = re.compile(r"(?<!\d)(19[5-9]\d|20[0-2]\d)(?!\d)")

TOKEN_RX = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?")
EMAIL_RX = re.compile(r"(?<![\w.+-])[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}(?![\w-])")
SPELLED_EMAIL_RX = re.compile(
    r"(?i)(?<![\w])([a-z0-9]+(?:\s+(?:punto|guion|gui[oó]n bajo|raya)\s+[a-z0-9]+)*)\s+arroba\s+"
    r"([a-z0-9]+(?:\s+punto\s+[a-z0-9]+)+)(?![\w])"
)
PHONE_RX = re.compile(r"(?<![\d+])(?:\+?57[\s.-]?)?\(?3\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)")
NUMBER_RX = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.\s]\d{3}){1,3}|\d{6,10})(?![\d]|[.,]\d)")
ID_CUE = re.compile(r"(?i)(?:\bc\.?\s?c\.?|c[ée]dula|documento|identificaci[oó]n|\bc\.?e\.?\b|\bnit\b|\bt\.?i\.?\b|\bid\b|n[uú]mero de identificaci[oó]n)[\s:#.,n°ºo]*(?:es\s+|del\s+titular\s+|:)?\s*$")
PLATE_RX = re.compile(r"(?<![A-Za-z0-9])([A-Z]{3})([- ]?)(\d{3}|\d{2}[A-Z])(?![A-Za-z0-9])")
PLATE_STOP = {"USD", "COP", "EUR", "MXN", "PQR", "INC", "CEO", "CTO", "CFO", "COO", "SOAT", "API", "PDF", "IVA", "GMF"}
PASSPORT_RX = re.compile(r"(?i)(?:pasaporte|passport)(?:\s+(?:n[°ºo.]*|number|no\.?|is|es|n[uú]mero))*\s*[:#]?\s*([A-Z]{1,3}\d{6,8})\b")
ADDRESS_RX = re.compile(
    r"(?i)(?<![\w])(?:calle|cl|carrera|cra|cr|kr|kra|diagonal|dg|transversal|tv|trans|avenida|av|ak|ac|autopista|circular|cq)"
    r"\.?\s+\d{1,3}\s?[a-z]?(?:\s+bis)?(?:\s+[a-z](?![\w]))?(?:\s+(?:sur|norte|este|oeste))?\s*(?:#|no\.?|n°|nº)\s*\d{1,3}\s?[a-z]?\s*-\s*\d{1,3}"
    r"(?:\s+(?:sur|norte|este))?(?:\s+(?:apto|apartamento|ap|of|oficina|casa|int|interior|torre|bloque|local|piso)\.?\s*\d{1,4}[a-z]?)*"
)
ISO_DATE_RX = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{2})-(\d{2})(?!\d)")
SLASH_DATE_RX = re.compile(r"(?<!\d)(\d{2})/(\d{2})/((?:19|20)\d{2})(?!\d)")
MENTION_RX = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")
TABLE_KEY_RX = re.compile(r"\b(CL-\d{4,6}|TX-\d{4,7}|PQR-\d{4}-\d{3,5}|KP-\d{3})\b")


def ntoks(text: str) -> tuple[str, ...]:
    return tuple(norm(m.group()) for m in TOKEN_RX.finditer(text))


def is_given(token: str) -> bool:
    return fakes.is_given_name(token)


def split_name(full: str) -> tuple[list[str], list[str]]:
    """'Tomás Felipe Corredor Ibarra' -> (['Tomás', 'Felipe'], ['Corredor', 'Ibarra'])."""
    raw = full.split()
    parts: list[str] = []
    i = 0
    while i < len(raw):
        t = raw[i]
        if norm(t) in PARTICLE_START and i + 1 < len(raw) and parts:
            j = i + 1
            chunk = [t]
            while j < len(raw) and norm(raw[j]) in PARTICLE_MID:
                chunk.append(raw[j])
                j += 1
            if j < len(raw):
                chunk.append(raw[j])
                j += 1
            parts.append(" ".join(chunk))
            i = j
        else:
            parts.append(t)
            i += 1
    if len(parts) <= 1:
        return parts, []
    if len(parts) == 2:
        return parts[:1], parts[1:]
    n_given = 2 if is_given(parts[1]) and len(parts) >= 3 else 1
    return parts[:n_given], parts[n_given:]


# ------------------------------------------------------------------ people ---

@dataclass
class Person:
    pid: str
    kind: str  # customer | employee | user | external
    given: list[str]
    surnames: list[str]
    gender: str | None = None
    city: str = ""
    ids: dict[str, set[str]] = field(default_factory=dict)
    originals: set[str] = field(default_factory=set)
    records: set[str] = field(default_factory=set)
    rendered: dict[str, set[str]] = field(default_factory=dict)

    @property
    def full(self) -> str:
        return " ".join(self.given + self.surnames)

    def add_id(self, kind: str, value: str) -> None:
        if value:
            self.ids.setdefault(kind, set()).add(value)


def _valid_iso(s: str) -> bool:
    try:
        _dt.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def canon(kind: str, value: str) -> str:
    v = value.strip()
    if kind in ("cedula", "phone", "account"):
        d = only_digits(v)
        if kind == "phone" and len(d) == 12 and d.startswith("57"):
            d = d[2:]
        return d
    if kind in ("email", "handle"):
        return v.lower()
    if kind in ("plate", "passport"):
        return re.sub(r"[\s-]", "", v).upper()
    if kind == "address":
        return norm(v)
    return v


@dataclass
class Ctx:
    record_id: str
    author: str | None = None
    owner: str | None = None  # the person a record is about (table row owner / thread customer)
    near: set[str] = field(default_factory=set)  # persons in context (thread participants, row owner)
    filename: bool = False
    # Every text of the record (all fields), and the persons it names in full or by a hard
    # identifier: computed on the first given-name-only mention that needs it.
    record_text: str = ""
    named: set[str] | None = None


class Engine:
    def __init__(self, factory: "fakes.PseudonymFactory"):
        self.f = factory
        self.persons: dict[str, Person] = {}
        self.alias: dict[str, str] = {}
        self.name_index: dict[str, list[tuple[tuple[str, ...], int, int, str]]] = {}
        self.id_index: dict[tuple[str, str], set[str]] = {}
        self.memo: dict[str, str] = {}
        self.kept_seen: dict[str, set[str]] = {}
        self.warnings: list[str] = []
        # Chat context of the last full run, persisted so live /anonymize sees what the batch
        # saw: thread_id -> {"near": [pids], "owner": pid | None}, and author key -> pid
        # ("" when the batch had no person for that author).
        self.threads: dict[str, dict] = {}
        self.authors: dict[str, str] = {}

    # ------------------------------------------------------------ registry --
    def resolve_pid(self, pid: str | None) -> str | None:
        seen = set()
        while pid in self.alias and pid not in seen:
            seen.add(pid)
            pid = self.alias[pid]
        return pid

    def person(self, pid: str) -> Person:
        return self.persons[self.resolve_pid(pid)]

    def add_person(self, pid: str, kind: str, full_name: str, gender: str | None = None, city: str = "") -> Person:
        given, surnames = split_name(full_name) if full_name else ([], [])
        if gender is None and given:
            gender = fakes.guess_gender(given[0])
        p = Person(pid=pid, kind=kind, given=given, surnames=surnames, gender=gender, city=city)
        self.persons[pid] = p
        self.index_names(p)
        return p

    def index_names(self, p: Person) -> None:
        g, s = p.given, p.surnames
        if not g:
            return
        forms: list[tuple[list[str], int, int]] = []
        if s:
            forms.append((g + s, len(g), len(s)))
            forms.append((g + s[:1], len(g), 1))
            if len(g) > 1:
                forms.append((g[:1] + s[:1], 1, 1))
                forms.append((g[:1] + s, 1, len(s)))
            if len(s) > 1:
                forms.append((g + s[:2], len(g), 2))
        if len(g) > 1:
            forms.append((g, len(g), 0))
        forms.append((g[:1], 1, 0))
        seen = set()
        for words, ng, ns in forms:
            toks = ntoks(" ".join(words))
            if not toks or toks in seen:
                continue
            seen.add(toks)
            self.name_index.setdefault(toks[0], []).append((toks, ng, ns, p.pid))

    def index_id(self, pid: str, kind: str, value: str) -> None:
        c = canon(kind, value)
        if not c:
            return
        self.person(pid).add_id(kind, c)
        self.id_index.setdefault((kind, c), set()).add(self.resolve_pid(pid))

    def merge(self, src: str, dst: str) -> None:
        """Make src an alias of dst (same real person)."""
        src, dst = self.resolve_pid(src), self.resolve_pid(dst)
        if src == dst:
            return
        ps, pd = self.persons[src], self.persons[dst]
        for kind, vals in ps.ids.items():
            for v in vals:
                pd.add_id(kind, v)
                self.id_index.setdefault((kind, v), set()).discard(src)
                self.id_index[(kind, v)].add(dst)
        for lst in self.name_index.values():
            for i, (toks, ng, ns, pid) in enumerate(lst):
                if pid == src:
                    lst[i] = (toks, ng, ns, dst)
        self.alias[src] = dst
        del self.persons[src]

    def candidates_by_name(self, full_name: str) -> set[str]:
        toks = ntoks(full_name)
        out = set()
        for ftoks, ng, ns, pid in self.name_index.get(toks[0] if toks else "", []):
            if ftoks == toks and ns > 0:
                out.add(self.resolve_pid(pid))
        return out

    # ---------------------------------------------------------- pseudonyms --
    def pname(self, p: Person) -> dict:
        key = f"name:{p.pid}"
        if key not in self.memo:
            res = self.f.name(p.pid, p.gender, max(1, len(p.given)), 2)
            self.memo[key] = "|".join([" ".join(res["given"]), " ".join(res["surnames"])])
        given, surnames = self.memo[key].split("|")
        g, s = given.split(), surnames.split()
        return {"given": g, "surnames": s, "short": " ".join(g + s[:1]), "full": " ".join(g + s)}

    def pseudo(self, kind: str, p: Person, original: str) -> str:
        c = canon(kind, original)
        key = f"{kind}:{p.pid}:{c}"
        if key not in self.memo:
            if kind == "email":
                val = self.f.email(f"{p.pid}:{c}", c, self.pname(p))
            elif kind == "cedula":
                val = self.f.cedula(f"{p.pid}:{c}", c)
            elif kind == "phone":
                val = self.f.phone(f"{p.pid}:{c}", c)
            elif kind == "account":
                val = self.f.account(f"{p.pid}:{c}", c)
            elif kind == "address":
                val = self.f.address(f"{p.pid}:{c}", original.strip())
            elif kind == "birth":
                val = self.f.birth(f"{p.pid}:{c}", c)
            elif kind == "plate":
                val = self.f.plate(f"{p.pid}:{c}", c)
            elif kind == "passport":
                val = self.f.passport(f"{p.pid}:{c}", c)
            elif kind == "handle":
                val = self.f.handle(f"{p.pid}:{c}", c, self.pname(p))
            else:
                raise ValueError(kind)
            self.memo[key] = val
        return self.memo[key]

    def note(self, p: Person, rec_id: str, original: str, kind: str, rendered: str) -> None:
        p.records.add(rec_id)
        if original:
            p.originals.add(original)
        if rendered:
            p.rendered.setdefault(kind, set()).add(rendered)

    # ---------------------------------------------------------- resolution --
    def pick(self, pids: set[str], ctx: Ctx, text: str = "") -> str | None:
        pids = {self.resolve_pid(p) for p in pids}
        if not pids:
            return None
        if len(pids) == 1:
            return next(iter(pids))
        for scope in ([ctx.author], [ctx.owner], ctx.near):
            hit = pids & {self.resolve_pid(x) for x in scope if x}
            if len(hit) == 1:
                return next(iter(hit))
        if text:
            ev = self.evidence(text) & pids
            if len(ev) == 1:
                return next(iter(ev))
        self.warnings.append(f"ambiguous {sorted(pids)} in {ctx.record_id}")
        return sorted(pids)[0]

    def evidence(self, text: str) -> set[str]:
        """Persons pointed to by hard identifiers in a piece of text."""
        out: set[str] = set()
        for m in EMAIL_RX.finditer(text):
            out |= self.id_index.get(("email", canon("email", m.group())), set())
        for m in NUMBER_RX.finditer(text):
            d = only_digits(m.group())
            out |= self.id_index.get(("cedula", d), set()) | self.id_index.get(("phone", d), set())
        for m in TABLE_KEY_RX.finditer(text):
            out |= self.id_index.get(("key", m.group()), set())
        return {self.resolve_pid(p) for p in out}

    def owner_for_unknown(self, ctx: Ctx, kind: str, value: str) -> Person:
        if ctx.owner and self.resolve_pid(ctx.owner) in self.persons:
            return self.person(ctx.owner)
        pid = f"x:{kind}:{canon(kind, value)}"
        if pid not in self.persons:
            self.add_person(pid, "external", "")
        return self.persons[pid]

    # ------------------------------------------------------------- spans ----
    def find_spans(self, text: str, ctx: Ctx) -> list[tuple[int, int, str, str]]:
        """Return (start, end, replacement, kind) for every personal datum in text."""
        spans: list[tuple[int, int, str, str, str, str]] = []  # start,end,repl,kind,pid,original

        def add(s: int, e: int, repl: str, kind: str, p: Person, original: str, rendered_kind: str, rendered_val: str):
            spans.append((s, e, repl, kind, p.pid, original))
            self.note(p, ctx.record_id, original, rendered_kind, rendered_val)

        # e-mails
        for m in EMAIL_RX.finditer(text):
            email = m.group()
            local = email.split("@")[0].lower()
            pids = self.id_index.get(("email", canon("email", email)), set())
            if not pids and local in ROLE_MAILBOXES:
                continue
            p = self.person(self.pick(pids, ctx, text)) if pids else self.owner_for_unknown(ctx, "email", email)
            if not pids:
                self.index_id(p.pid, "email", email)
            val = self.pseudo("email", p, email)
            add(m.start(), m.end(), val, "email", p, email, "email", val)
        for m in SPELLED_EMAIL_RX.finditer(text):
            local = re.sub(r"(?i)\s+punto\s+", ".", m.group(1))
            local = re.sub(r"(?i)\s+gui[oó]n bajo\s+", "_", local)
            local = re.sub(r"(?i)\s+(?:guion|raya)\s+", "-", local)
            domain = re.sub(r"(?i)\s+punto\s+", ".", m.group(2))
            email = f"{local}@{domain}".lower()
            pids = self.id_index.get(("email", email), set())
            p = self.person(self.pick(pids, ctx, text)) if pids else self.owner_for_unknown(ctx, "email", email)
            if not pids:
                self.index_id(p.pid, "email", email)
            val = self.pseudo("email", p, email)
            lp, dp = val.split("@", 1)
            spelled = lp.replace(".", " punto ").replace("_", " guion bajo ").replace("-", " guion ")
            spelled = f"{spelled} arroba {dp.replace('.', ' punto ')}"
            if m.group().isupper():
                spelled = spelled.upper()
            add(m.start(), m.end(), spelled, "email", p, m.group(), "email_spelled", val)
            p.originals.add(email)
        # phones
        for m in PHONE_RX.finditer(text):
            surf = m.group()
            d = canon("phone", surf)
            if len(d) != 10:
                continue
            pids = self.id_index.get(("phone", d), set())
            p = self.person(self.pick(pids, ctx, text)) if pids else self.owner_for_unknown(ctx, "phone", d)
            if not pids:
                self.index_id(p.pid, "phone", d)
            val = self.pseudo("phone", p, d)
            nd = val if len(only_digits(surf)) == 10 else "57" + val
            add(m.start(), m.end(), fakes.format_like(surf, nd), "phone", p, surf, "phone", val)
        # identity numbers (registry match, or a cue such as "cc", "cédula")
        for m in NUMBER_RX.finditer(text):
            surf = m.group(1)
            d = only_digits(surf)
            if not 6 <= len(d) <= 10:
                continue
            kind = None
            pids: set[str] = set()
            for k in ("cedula", "phone", "account"):
                if self.id_index.get((k, d)):
                    kind, pids = k, self.id_index[(k, d)]
                    break
            if kind is None:
                if ID_CUE.search(text[max(0, m.start() - 40):m.start()]) and not (len(d) == 10 and d.startswith("3")):
                    kind = "cedula"
                else:
                    continue
            p = self.person(self.pick(pids, ctx, text)) if pids else self.owner_for_unknown(ctx, kind, d)
            if not pids:
                self.index_id(p.pid, kind, d)
            val = self.pseudo(kind, p, d)
            add(m.start(1), m.end(1), fakes.format_like(surf, val), kind, p, surf, kind, val)
        # plates
        for m in PLATE_RX.finditer(text):
            if m.group(1) in PLATE_STOP:
                continue
            surf = m.group()
            c = canon("plate", surf)
            pids = self.id_index.get(("plate", c), set())
            p = self.person(self.pick(pids, ctx, text)) if pids else self.owner_for_unknown(ctx, "plate", c)
            if not pids:
                self.index_id(p.pid, "plate", c)
            val = self.pseudo("plate", p, surf)
            add(m.start(), m.end(), val, "plate", p, surf, "plate", val)
        # passports
        for m in PASSPORT_RX.finditer(text):
            surf = m.group(1)
            c = canon("passport", surf)
            pids = self.id_index.get(("passport", c), set())
            p = self.person(self.pick(pids, ctx, text)) if pids else self.owner_for_unknown(ctx, "passport", c)
            if not pids:
                self.index_id(p.pid, "passport", c)
            val = self.pseudo("passport", p, surf)
            add(m.start(1), m.end(1), val, "passport", p, surf, "passport", val)
        # addresses
        for m in ADDRESS_RX.finditer(text):
            surf = m.group().rstrip(" ,.")
            c = canon("address", surf)
            pids = self.id_index.get(("address", c), set())
            p = self.person(self.pick(pids, ctx, text)) if pids else self.owner_for_unknown(ctx, "address", c)
            if not pids:
                self.index_id(p.pid, "address", surf)
            val = self.pseudo("address", p, surf)
            add(m.start(), m.start() + len(surf), val, "address", p, surf, "address", val)
        # birth dates known in the registry
        for m in ISO_DATE_RX.finditer(text):
            pids = self.id_index.get(("birth", m.group()), set())
            if not pids:
                continue
            p = self.person(self.pick(pids, ctx, text))
            val = self.pseudo("birth", p, m.group())
            add(m.start(), m.end(), val, "birth", p, m.group(), "birth_iso", val)
        # Slash dates: Spanish text writes day first, the English documents month first
        # ("DOB 03/26/1984"), so try both readings against the registry. When both are
        # someone's birth date, a person in this record's context wins, then day first.
        context = {self.resolve_pid(x) for x in [ctx.author, ctx.owner, *ctx.near] if x}
        for m in SLASH_DATE_RX.finditer(text):
            a, b, y = m.group(1), m.group(2), m.group(3)
            cands = [(iso, dayfirst) for iso, dayfirst in ((f"{y}-{b}-{a}", True), (f"{y}-{a}-{b}", False))
                     if _valid_iso(iso) and self.id_index.get(("birth", iso))]
            if not cands:
                continue
            cands.sort(key=lambda c: not ({self.resolve_pid(x) for x in self.id_index[("birth", c[0])]} & context))
            iso, dayfirst = cands[0]
            p = self.person(self.pick(self.id_index[("birth", iso)], ctx, text))
            val = self.pseudo("birth", p, iso)
            # same factory key as pseudo() -> same shifted date, written in the original layout
            out = self.f.birth(f"{p.pid}:{canon('birth', iso)}", m.group(), dayfirst=dayfirst)
            add(m.start(), m.end(), out, "birth", p, m.group(), "birth_iso", val)
        # handles (chat usernames, pqrs agents)
        for m in re.finditer(r"(?<![\w.-])[a-z][a-z0-9]*(?:[._][a-z0-9]+)*(?![\w@-]|\.\w)", text):
            pids = self.id_index.get(("handle", m.group().lower()), set())
            if not pids:
                continue
            p = self.person(self.pick(pids, ctx, text))
            val = self.pseudo("handle", p, m.group())
            add(m.start(), m.end(), val, "handle", p, m.group(), "handle", val)
        # names
        spans.extend(self.find_names(text, ctx))
        return self._resolve_overlaps(spans)

    def _resolve_overlaps(self, spans):
        spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
        out = []
        last_end = -1
        for s in spans:
            if s[0] >= last_end:
                out.append(s)
                last_end = s[1]
        return out

    def find_names(self, text: str, ctx: Ctx):
        toks = [(m.start(), m.end(), m.group(), norm(m.group())) for m in TOKEN_RX.finditer(text)]
        spans = []
        i = 0
        while i < len(toks):
            best = None
            for ftoks, ng, ns, pid in self.name_index.get(toks[i][3], []):
                n = len(ftoks)
                if i + n > len(toks) or (best and n < best[0]):
                    continue
                if all(toks[i + k][3] == ftoks[k] for k in range(n)) and self._gaps_ok(text, toks, i, n):
                    if best is None or n > best[0]:
                        best = (n, ng, ns, {pid})
                    elif n == best[0]:
                        best[3].add(pid)
            if best:
                n, ng, ns, pids = best
                start, end = toks[i][0], toks[i + n - 1][1]
                surf = text[start:end]
                weak = ns == 0
                if weak:
                    pid = self._weak_pick(pids, ctx, text, start, surf)
                else:
                    pid = self.pick(pids, ctx, text)
                if pid and not self._is_kept_at(text, start, end):
                    p = self.persons[pid]
                    repl = self.render_name(p, ng, ns, surf, text, start, end)
                    spans.append((start, end, repl, "name", p.pid, surf))
                    self.note(p, ctx.record_id, surf if not weak else "", "name", repl)
                    if weak:
                        p.originals.add(surf)
                    i += n
                    continue
            # unknown full names: Given + Capitalized surname(s)
            span = self._unknown_name(text, toks, i, ctx)
            if span:
                spans.append(span[:6])
                i += span[6]
                continue
            i += 1
        return spans

    def _gaps_ok(self, text, toks, i, n) -> bool:
        seps = {text[toks[i + k][1]:toks[i + k + 1][0]] for k in range(n - 1)}
        if not seps:
            return True
        if all(s == "_" for s in seps) or all(s == "-" for s in seps):
            return True
        return all(s.strip() == "" and 0 < len(s) <= 3 for s in seps)

    def named_in(self, text: str) -> set[str]:
        """Persons a text names in full (a known form with a surname and a single
        candidate) or points to by a hard identifier (e-mail, cédula, phone, record key)."""
        out = set(self.evidence(text))
        toks = [(m.start(), m.end(), m.group(), norm(m.group())) for m in TOKEN_RX.finditer(text)]
        i = 0
        while i < len(toks):
            best = None
            for ftoks, ng, ns, pid in self.name_index.get(toks[i][3], []):
                n = len(ftoks)
                if i + n > len(toks) or (best and n < best[0]):
                    continue
                if all(toks[i + k][3] == ftoks[k] for k in range(n)) and self._gaps_ok(text, toks, i, n):
                    if best is None or n > best[0]:
                        best = (n, ns, {self.resolve_pid(pid)})
                    elif n == best[0]:
                        best[2].add(self.resolve_pid(pid))
            if best:
                n, ns, pids = best
                start, end = toks[i][0], toks[i + n - 1][1]
                if ns > 0 and len(pids) == 1 and not self._is_kept_at(text, start, end):
                    out |= pids
                i += n
            else:
                i += 1
        return out

    def _weak_pick(self, pids, ctx, text, start, surf) -> str | None:
        pids = {self.resolve_pid(p) for p in pids}
        near = {self.resolve_pid(x) for x in ([ctx.author, ctx.owner] + list(ctx.near)) if x}
        hit = pids & near
        if not surf[:1].isupper() and not ctx.filename:
            return None
        # Two-pass over the record: a given-name-only mention ("Tomás Felipe", "Joaquín")
        # goes to the one candidate the same record names in full or by a hard identifier.
        if ctx.named is None:
            ctx.named = {self.resolve_pid(x) for x in self.named_in(ctx.record_text or text)}
        named = pids & ctx.named
        if len(named) == 1:
            return next(iter(named))
        if len(hit) == 1:
            return next(iter(hit))
        if NAME_CUE.search(text[max(0, start - 40):start]) and len(pids) == 1:
            return next(iter(pids))
        return None

    def _is_kept_at(self, text, start, end) -> bool:
        window = norm(text[max(0, start - 25):min(len(text), end + 25)])
        surf = norm(text[start:end])
        return any(k in window and surf in k for k in _KEPT_NORM if len(k) > len(surf))

    def _unknown_name(self, text, toks, i, ctx):
        s0, e0, raw0, n0 = toks[i]
        upper_ok = raw0[:1].isupper()
        if not (upper_ok or ctx.filename) or len(n0) < 3 or not is_given(raw0):
            return None
        j = i + 1
        words = [raw0]
        while j < len(toks) and len(words) < 4 and self._gaps_ok(text, toks, j - 1, 2):
            raw = toks[j][2]
            if not (raw[:1].isupper() or ctx.filename) or len(raw) < 2 or norm(raw) in fakes.NON_NAME_WORDS:
                break
            words.append(raw)
            j += 1
        if len(words) < 2 or all(is_given(w) for w in words):
            return None
        start, end = s0, toks[j - 1][1]
        surf = text[start:end]
        if norm(surf) in _KEPT_NORM or self._is_kept_at(text, start, end):
            self.kept_seen.setdefault(surf, set()).add(ctx.record_id)
            return None
        pid = f"x:name:{' '.join(ntoks(surf))}"
        if pid not in self.persons:
            self.add_person(pid, "external", " ".join(words))
        p = self.persons[pid]
        given, surnames = split_name(" ".join(words))
        repl = self.render_name(p, len(given), len(surnames), surf, text, start, end)
        self.note(p, ctx.record_id, surf, "name", repl)
        return (start, end, repl, "name", pid, surf, j - i)

    def render_name(self, p: Person, ng: int, ns: int, surf: str, text: str, start: int, end: int) -> str:
        pn = self.pname(p)
        given = pn["given"] if ng >= len(p.given) else pn["given"][:ng]
        out = " ".join(given + pn["surnames"][:ns])
        if "_" in surf:
            return fakes.slug(out)
        if "-" in surf and " " not in surf:
            return fakes.slug(out).replace("_", "-")
        if surf.isupper() and len(surf) > 1:
            out = out.upper()
        elif surf.islower():
            out = out.lower()
        if strip_accents(surf) == surf and strip_accents(p.full) != p.full:
            out = strip_accents(out)
        return out

    # -------------------------------------------------------------- apply ---
    def anonymize_text(self, text: str, ctx: Ctx) -> str:
        if not text:
            return text
        spans = self.find_spans(text, ctx)
        out = []
        pos = 0
        for s, e, repl, *_ in spans:
            out.append(text[pos:s])
            out.append(repl)
            pos = e
        out.append(text[pos:])
        result = "".join(out)
        self.collect_kept(text, ctx.record_id)
        owner = self.persons.get(self.resolve_pid(ctx.owner)) if ctx.owner else None
        return self.generalize_quasi(result, owner.city if owner else "")

    def collect_kept(self, text: str, rec_id: str) -> None:
        nt = norm(text)
        for term in KEPT_TERMS:
            k = norm(term)
            if len(k) >= 4 and re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", nt):
                self.kept_seen.setdefault(term, set()).add(rec_id)

    def generalize_quasi(self, text: str, city: str = "") -> str:
        """Occupation + barrio + year in a self-description: generalize all three.

        city is the record owner's city, used for barrios that exist in several cities
        (Castilla: Medellín and Bogotá; Boston: Medellín and Barranquilla)."""
        # One precompiled alternation (longest term first) instead of one regex per term:
        # the per-term loop recompiled ~1,000 patterns per text (the re cache holds 512).
        # Spans are found on the original text and replaced right-to-left, so a sector
        # phrase already written ("estudiante de educación superior") is never re-matched.
        spans = [m for m in fakes.OCCUPATION_RX.finditer(text)
                 if OCC_CUE.search(text[max(0, m.start() - 40):m.start()])]
        if not spans:
            return text
        out = text
        for m in reversed(spans):
            out = out[:m.start()] + fakes.occupation_sector(m.group()) + out[m.end():]
        home = fakes.canonical_city(city) if city else ""
        for barrio_norm, barrio_city in list(fakes.CITY_OF_BARRIO.items()):
            if len(barrio_norm) < 4:
                continue
            for m in re.finditer(r"[^\W\d_]+(?:\s+[^\W\d_]+){0,3}", out):
                pass
            rx = re.compile(r"(?<![\w])" + r"\s+".join(re.escape(w) for w in barrio_norm.split()) + r"(?![\w])", re.I)
            plain = strip_accents(out)
            m = rx.search(plain)
            if m and out[m.start():m.end()][:1].isupper():
                cities = fakes.CITIES_OF_BARRIO.get(barrio_norm, [barrio_city])
                out = out[:m.start()] + (home if home in cities else barrio_city) + out[m.end():]
        out = YEAR_RX.sub("hace unos años", out, count=1) if re.search(r"(?i)\b(?:en|desde|año)\s+(?:19|20)\d{2}\b", out) else out
        return out
