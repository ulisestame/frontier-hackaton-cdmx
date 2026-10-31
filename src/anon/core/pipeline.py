"""Pipeline entry points used by the HTTP service.

Contract (stable; the service layer depends on it):
- run_pipeline(...) regenerates the four output files into out_dir from the sources API.
- anonymize_live(...) anonymizes new records with the pseudonyms persisted by the last run.

State that must survive between runs (the sources grow mid-event and every person
already published must keep exactly the same pseudonym) lives in state_dir/state.json.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from .. import fakes
from .engine import TABLE_KEY_RX, Ctx, Engine, Person, canon, norm
from .textnorm import contains, is_bare_name, record_text

SECRET = os.environ.get("ANON_SECRET", "kipu-frontier-2026-secret").encode()
STATE_FILE = "state.json"
_LIVE_LOCK = threading.Lock()
_LIVE_CACHE: dict = {}


# ------------------------------------------------------------------ state ---

def _blocked_tokens(engine: Engine) -> set[str]:
    out = set()
    for p in engine.persons.values():
        for w in p.given + p.surnames:
            for t in w.split():
                out.add(fakes.normalize_token(t))
    return out


_RESERVED_KINDS = ("birth", "cedula", "phone", "email", "plate", "passport", "account", "handle", "address")


def _reserve_real_values(eng: Engine) -> None:
    """Tell the factory every real identifier known so far, before it generates anything.

    The validator rejects the output if any person's original form appears anywhere, and
    the factory only auto-reserves the originals it has already been asked about. Birth
    dates are the risky kind: in a ~20k-day space, about one pseudonym date per run
    landed on another person's real date when reservation followed table order.
    """
    for kind, value in list(eng.id_index):
        if kind in _RESERVED_KINDS and value:
            eng.f.reserve(kind, [value])


def load_state(state_dir: Path) -> dict:
    f = state_dir / STATE_FILE
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    return {}


def save_state(state_dir: Path, engine: Engine, entity_ids: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "memo": engine.memo,
        "entity_ids": entity_ids,
        "factory": engine.f.export_state(),
        "alias": engine.alias,
        "persons": {
            pid: {
                "kind": p.kind, "given": p.given, "surnames": p.surnames, "gender": p.gender,
                "city": p.city, "ids": {k: sorted(v) for k, v in p.ids.items()},
            }
            for pid, p in engine.persons.items()
        },
    }
    fd, tmp = tempfile.mkstemp(dir=state_dir, prefix=".state.")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    os.replace(tmp, state_dir / STATE_FILE)


def engine_from_state(state: dict) -> Engine:
    factory = fakes.PseudonymFactory(SECRET, set(), state.get("factory"))
    eng = Engine(factory)
    eng.memo = dict(state.get("memo", {}))
    for pid, d in state.get("persons", {}).items():
        p = Person(pid=pid, kind=d["kind"], given=d["given"], surnames=d["surnames"],
                   gender=d.get("gender"), city=d.get("city", ""))
        eng.persons[pid] = p
        eng.index_names(p)
        for kind, vals in d.get("ids", {}).items():
            for v in vals:
                p.add_id(kind, v)
                eng.id_index.setdefault((kind, v), set()).add(pid)
    eng.alias = dict(state.get("alias", {}))
    return eng


# --------------------------------------------------------------- registry ---

def build_registry(eng: Engine, corpus) -> dict:
    """Identity registry from structured sources. Returns per-thread context."""
    rows = corpus.tables
    for r in rows:
        c = r["columns"]
        if r["table"] == "clientes":
            pid = f"cl:{c.get('cliente_id')}"
            if pid not in eng.persons:
                eng.add_person(pid, "customer", c.get("nombre_completo", ""), city=c.get("ciudad", ""))
            for kind, col in (("cedula", "num_doc"), ("email", "correo"), ("phone", "celular"),
                              ("address", "direccion"), ("birth", "fecha_nacimiento")):
                eng.index_id(pid, kind, c.get(col, ""))
            eng.id_index.setdefault(("key", c.get("cliente_id", "")), set()).add(pid)
        elif r["table"] == "empleados":
            pid = f"kp:{c.get('id')}"
            if pid not in eng.persons:
                eng.add_person(pid, "employee", c.get("nombre", ""), city=c.get("ciudad", ""))
            for kind, col in (("email", "correo"), ("phone", "celular"), ("cedula", "documento"),
                              ("birth", "fecha_nacimiento")):
                eng.index_id(pid, kind, c.get(col, ""))
            mail = c.get("correo", "")
            if "@" in mail:
                eng.index_id(pid, "handle", mail.split("@")[0])
            eng.id_index.setdefault(("key", c.get("id", "")), set()).add(pid)
    for r in rows:
        c = r["columns"]
        owner = eng.id_index.get(("key", c.get("cliente_id", "")), set())
        if r["table"] == "pqrs" and owner:
            pid = next(iter(owner))
            eng.id_index.setdefault(("key", c.get("radicado", "")), set()).add(pid)
            if c.get("cedula"):
                eng.index_id(pid, "cedula", c["cedula"])
        elif r["table"] == "transacciones" and owner:
            eng.id_index.setdefault(("key", c.get("tx_id", "")), set()).add(next(iter(owner)))

    # chat users -> registry persons
    ambiguous: dict[str, set[str]] = {}
    for uid, u in corpus.users.items():
        if u.get("is_bot"):
            continue
        prof = u.get("profile") or {}
        real = u.get("real_name") or prof.get("real_name") or u.get("name", "")
        email = (prof.get("email") or "").strip()
        upid = f"u:{uid}"
        cands = set(eng.id_index.get(("email", canon("email", email)), set())) if email else set()
        if not cands and real:
            cands = eng.candidates_by_name(real)
        if len(cands) == 1:
            target = next(iter(cands))
            eng.alias[upid] = target
        else:
            if upid not in eng.persons:
                eng.add_person(upid, "employee" if email.endswith("@kipupay.co") else "user", real)
            if len(cands) > 1:
                ambiguous[upid] = cands
        if email:
            eng.index_id(upid, "email", email)
        if prof.get("phone"):
            eng.index_id(upid, "phone", prof["phone"])
        if u.get("name"):
            eng.index_id(upid, "handle", u["name"])

    # threads and evidence-based linking for homonyms
    threads: dict[str, dict] = {}
    for m in corpus.chats:
        t = threads.setdefault(m["thread_id"], {"users": [], "text": []})
        if m.get("_user") and not m.get("_is_bot"):
            t["users"].append(m["_user"])
        t["text"].append(m.get("text", ""))
    for upid, cands in ambiguous.items():
        uid = upid[2:]
        text = "\n".join(x for t in threads.values() if uid in t["users"] for x in t["text"])
        ev = eng.evidence(text) & cands
        if len(ev) == 1:
            eng.merge(upid, next(iter(ev)))
    # Users with no name match (deactivated accounts, nicknames): link them only through hard
    # identifiers they wrote themselves (their own cédula, phone or e-mail), never by name.
    own_text: dict[str, list[str]] = {}
    for m in corpus.chats:
        if m.get("_user") and not m.get("_is_bot"):
            own_text.setdefault(m["_user"], []).append(m.get("text", ""))
    for uid, texts in own_text.items():
        upid = f"u:{uid}"
        if upid in eng.alias or upid in ambiguous or upid not in eng.persons:
            continue
        if eng.persons[upid].kind != "user":
            continue
        ev = {p for p in eng.evidence("\n".join(texts)) if p != upid and eng.persons[p].kind == "customer"}
        if len(ev) == 1:
            eng.merge(upid, next(iter(ev)))
    return threads


def thread_context(eng: Engine, thread: dict) -> tuple[set[str], str | None]:
    near = {eng.resolve_pid(f"u:{u}") for u in thread["users"]}
    near = {p for p in near if p in eng.persons}
    customers = [p for p in near if eng.persons[p].kind in ("customer", "user")]
    owner = customers[0] if len(customers) == 1 else None
    return near, owner


# ------------------------------------------------------------- processing ---

def process_table_row(eng: Engine, r: dict) -> dict:
    c = dict(r["columns"])
    rid = r["id"]
    table = r["table"]
    owner_pids = eng.id_index.get(("key", c.get("cliente_id") or c.get("id") or ""), set())
    owner = eng.resolve_pid(next(iter(owner_pids))) if owner_pids else None
    ctx = Ctx(record_id=rid, owner=owner, near={owner} if owner else set())
    out = {}
    p = eng.persons.get(owner) if owner else None

    def ident(kind: str, value: str, fmt: bool = True) -> str:
        if not value or p is None:
            return value
        val = eng.pseudo(kind, p, value)
        rendered = fakes.format_like(value, val) if fmt and kind in ("cedula", "phone") else val
        eng.note(p, rid, value, "birth_iso" if kind == "birth" else kind, val)
        return rendered

    for k, v in c.items():
        v = "" if v is None else str(v)
        if table == "clientes" and p is not None:
            if k == "nombre_completo" and v:
                out[k] = eng.render_name(p, len(p.given), len(p.surnames), v, v, 0, len(v))
                eng.note(p, rid, v, "name", out[k])
                continue
            if k in ("num_doc", "correo", "celular", "direccion", "fecha_nacimiento"):
                kind = {"num_doc": "cedula", "correo": "email", "celular": "phone",
                        "direccion": "address", "fecha_nacimiento": "birth"}[k]
                out[k] = ident(kind, v)
                continue
            if k == "barrio" and v:
                out[k] = fakes.pseudo_barrio(p.pid, c.get("ciudad", ""), v)
                continue
            if k == "ocupacion" and v:
                out[k] = fakes.occupation_sector(v)
                continue
            if k in ("cliente_id", "tipo_doc", "ciudad", "fecha_vinculacion"):
                out[k] = v
                continue
        if table == "empleados" and p is not None:
            if k == "nombre" and v:
                out[k] = eng.render_name(p, len(p.given), len(p.surnames), v, v, 0, len(v))
                eng.note(p, rid, v, "name", out[k])
                continue
            if k in ("correo", "celular", "documento", "fecha_nacimiento"):
                kind = {"correo": "email", "celular": "phone", "documento": "cedula",
                        "fecha_nacimiento": "birth"}[k]
                out[k] = ident(kind, v)
                continue
            if k in ("id", "cargo", "ciudad", "ingreso") or k.endswith("_tipo"):
                out[k] = v
                continue
        if table == "pqrs":
            if k == "cedula" and v and p is not None:
                out[k] = ident("cedula", v)
                continue
            if k == "agente" and v:
                pids = eng.id_index.get(("handle", v.lower()), set())
                if pids:
                    ap = eng.person(next(iter(pids)))
                    out[k] = eng.pseudo("handle", ap, v)
                    eng.note(ap, rid, v, "handle", out[k])
                    continue
            if k in ("radicado", "cliente_id", "ciudad", "fecha", "tipo", "estado"):
                out[k] = v
                continue
        if table == "transacciones" and k in ("tx_id", "fecha", "cliente_id", "tipo", "monto", "canal", "estado"):
            out[k] = v
            continue
        out[k] = eng.anonymize_text(v, ctx)
    return {"id": rid, "table": table, "columns": out}


def process_doc(eng: Engine, d: dict) -> dict:
    # Hard identifiers anywhere in the document (a cédula, a CL- key) decide homonyms in every field,
    # e.g. "Carta de mora - Rubén Ocampo" in the metadata title of a letter that carries the customer's CC.
    whole = " ".join([d.get("filename", ""), d.get("title", ""), d.get("body", "")] +
                     [str(v) for v in d.get("metadata", {}).values()])
    near = eng.evidence(whole)
    ctx = Ctx(record_id=d["id"], near=near)
    fctx = Ctx(record_id=d["id"], near=near, filename=True)
    return {
        "id": d["id"],
        "format": d["format"],
        "filename": eng.anonymize_text(d["filename"], fctx),
        "title": eng.anonymize_text(d.get("title", ""), ctx),
        "body": eng.anonymize_text(d.get("body", ""), ctx),
        "metadata": {k: eng.anonymize_text("" if v is None else str(v), ctx) for k, v in d.get("metadata", {}).items()},
    }


def process_chat(eng: Engine, m: dict, threads: dict) -> dict:
    near, owner = thread_context(eng, threads.get(m["thread_id"], {"users": []}))
    author_pid = eng.resolve_pid(f"u:{m['_user']}") if m.get("_user") else None
    if author_pid not in eng.persons:
        author_pid = None
    if author_pid and eng.persons[author_pid].kind in ("customer", "user"):
        owner = author_pid
    ctx = Ctx(record_id=m["id"], author=author_pid, owner=owner, near=near)
    author = m.get("author", "")
    if author_pid and not m.get("_is_bot"):
        p = eng.persons[author_pid]
        pn = eng.pname(p)
        author_out = pn["short"]
        eng.note(p, m["id"], author, "name", author_out)
    else:
        author_out = eng.anonymize_text(author, ctx) if author else author
    fctx = Ctx(record_id=m["id"], author=author_pid, owner=owner, near=near, filename=True)
    return {
        "id": m["id"],
        "thread_id": m["thread_id"],
        "author": author_out,
        "ts": m["ts"],
        "text": eng.anonymize_text(m.get("text", ""), ctx),
        "attachments": [{"filename": eng.anonymize_text(a.get("filename", ""), fctx)} for a in m.get("attachments", [])],
    }


# --------------------------------------------------------------- entities ---

class Haystack:
    def __init__(self, records: list[dict]):
        self.by_id = {r["id"]: record_text(r) for r in records}
        self.whole = "\n".join(self.by_id.values())

    def has(self, needle: str) -> bool:
        return contains(self.whole, needle)

    def in_records(self, rec_ids, needle: str) -> bool:
        return any(contains(self.by_id[r], needle) for r in rec_ids if r in self.by_id)


def build_entities(eng: Engine, records: list[dict], entity_ids: dict) -> tuple[list[dict], list[str]]:
    hay = Haystack(records)
    leaks: list[str] = []
    ents: list[dict] = []
    kept_originals: list[str] = [t for t in eng.kept_seen if len(t) >= 4]
    next_n = 1 + max([int(v.split("_")[1]) for v in entity_ids.values() if v.startswith("p_")] or [0])
    for pid in sorted(eng.persons):
        p = eng.persons[pid]
        if not p.records:
            continue
        if pid not in entity_ids:
            entity_ids[pid] = f"p_{next_n:03d}"
            next_n += 1
        recs = sorted(p.records)
        pseud: dict[str, str] = {}
        names = [eng.pname(p)["short"]] + sorted(p.rendered.get("name", set()), key=len, reverse=True) if p.given else []
        for cand in names:
            if hay.in_records(recs, cand):
                pseud["name"] = cand
                break
        for kind in ("email", "phone", "cedula", "address", "birth_iso", "plate", "passport", "account", "handle"):
            for cand in sorted(p.rendered.get(kind, set())):
                if hay.in_records(recs, cand):
                    pseud[kind] = cand
                    break
        if not pseud:
            continue
        originals = []
        for o in sorted(p.originals):
            if len(o) >= 3 and not is_bare_name(o) and not any(contains(k, o) for k in kept_originals) and hay.has(o):
                leaks.append(f"{entity_ids[pid]} {o!r}")
                continue
            originals.append(o)
        ents.append({"entity_id": entity_ids[pid], "type": "person", "originals": originals,
                     "pseudonyms": pseud, "records": recs})
    n = 1
    for term in sorted(eng.kept_seen):
        key = f"kept:{norm(term)}"
        if key not in entity_ids:
            entity_ids[key] = f"kept_{n:03d}"
        n += 1
        ents.append({"entity_id": entity_ids[key], "type": "organization_or_place", "originals": [term],
                     "pseudonyms": {}, "kept": True,
                     "reason": "organización, lugar, marca o figura pública; no es persona natural",
                     "records": sorted(r for r in eng.kept_seen[term] if r in hay.by_id)})
    return ents, leaks


# -------------------------------------------------------------------- run ---

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def anonymize_corpus(corpus, state_dir: Path, progress: Callable[[dict], None] = lambda e: None):
    prev = load_state(state_dir)
    eng = engine_from_state(prev) if prev else Engine(fakes.PseudonymFactory(SECRET, set(), None))
    threads = build_registry(eng, corpus)
    eng.f = fakes.PseudonymFactory(SECRET, _blocked_tokens(eng), prev.get("factory") if prev else None)
    _reserve_real_values(eng)
    progress({"stage": "registry", "persons": len(eng.persons)})
    tables = [process_table_row(eng, r) for r in corpus.tables]
    progress({"stage": "tables", "done": len(tables)})
    docs = [process_doc(eng, d) for d in corpus.docs]
    progress({"stage": "docs", "done": len(docs)})
    chats = [process_chat(eng, m, threads) for m in corpus.chats]
    progress({"stage": "chats", "done": len(chats)})
    entity_ids = dict(prev.get("entity_ids", {})) if prev else {}
    entities, leaks = build_entities(eng, chats + docs + tables, entity_ids)
    progress({"stage": "entities", "entities": len(entities), "leaks": len(leaks)})
    return eng, entity_ids, chats, docs, tables, entities, leaks


def run_pipeline(sources_url: str, token: str, out_dir: Path, state_dir: Path,
                 progress: Callable[[dict], None] = lambda _event: None) -> dict:
    from ..parse import load_corpus
    from ..sources import fetch_all

    t0 = time.time()
    raw_dir = Path(state_dir) / "raw" / time.strftime("%Y%m%d-%H%M%S")
    progress({"stage": "fetch"})
    fetch_all(sources_url, token, raw_dir)
    corpus = load_corpus(raw_dir)
    eng, entity_ids, chats, docs, tables, entities, leaks = anonymize_corpus(corpus, Path(state_dir), progress)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out_dir / "chats.jsonl", chats)
    _write_jsonl(out_dir / "docs.jsonl", docs)
    _write_jsonl(out_dir / "tables.jsonl", tables)
    (out_dir / "entities.json").write_text(json.dumps({"entities": entities}, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.json").write_text(json.dumps({"leaks": leaks, "warnings": eng.warnings[:500],
                                                     "seconds": round(time.time() - t0, 1)}, ensure_ascii=False, indent=1), encoding="utf-8")
    save_state(Path(state_dir), eng, entity_ids)
    # Keep one snapshot per run: rollback point, and the before/after evidence for the incident.
    hist = Path(state_dir) / "history"
    hist.mkdir(parents=True, exist_ok=True)
    (hist / f"state-{time.strftime('%Y%m%d-%H%M%S')}.json").write_bytes((Path(state_dir) / STATE_FILE).read_bytes())
    _LIVE_CACHE.clear()
    return {"records": {"chats": len(chats), "docs": len(docs), "tables": len(tables)},
            "tokens_in": 0, "tokens_out": 0}


# ------------------------------------------------------------------- live ---

def _live_engine(state_dir: Path) -> tuple[Engine, dict]:
    f = Path(state_dir) / STATE_FILE
    mtime = f.stat().st_mtime if f.exists() else 0
    if _LIVE_CACHE.get("mtime") != mtime:
        state = load_state(Path(state_dir))
        eng = engine_from_state(state)
        eng.f = fakes.PseudonymFactory(SECRET, _blocked_tokens(eng), state.get("factory"))
        _reserve_real_values(eng)
        _LIVE_CACHE.update({"mtime": mtime, "engine": eng, "entity_ids": dict(state.get("entity_ids", {}))})
    return _LIVE_CACHE["engine"], _LIVE_CACHE["entity_ids"]


def anonymize_live(source: str, records: list[dict], state_dir: Path) -> dict:
    with _LIVE_LOCK:
        eng, entity_ids = _live_engine(state_dir)
        for p in eng.persons.values():
            p.records.clear()
            p.originals.clear()
            p.rendered.clear()
        eng.kept_seen.clear()
        out = []
        for r in records:
            if source == "tables":
                out.append(process_table_row(eng, r))
            elif source == "docs":
                out.append(process_doc(eng, {**r, "metadata": r.get("metadata", {})}))
            else:
                author = r.get("author", "")
                cands = eng.candidates_by_name(author) if author else set()
                pid = eng.pick(cands, Ctx(record_id=r["id"]), r.get("text", "")) if cands else None
                if pid is None and author and author.lower() != "kipi":
                    pid = f"x:name:{' '.join(norm(author).split())}"
                    if pid not in eng.persons:
                        eng.add_person(pid, "external", author)
                m = {**r, "_user": None, "_is_bot": author.lower() == "kipi"}
                near = {pid} if pid else set()
                ctx = Ctx(record_id=r["id"], author=pid, owner=pid, near=near)
                rec = process_chat(eng, m, {})
                if pid:
                    p = eng.persons[pid]
                    rec["author"] = eng.pname(p)["short"]
                    eng.note(p, r["id"], author, "name", rec["author"])
                rec["text"] = eng.anonymize_text(r.get("text", ""), ctx)
                out.append(rec)
        ents, _ = build_entities(eng, out, entity_ids)
        ents = [e for e in ents if e.get("type") == "person"]
        # No state write here: a full run may be writing state.json from another process.
        # New people stay consistent in memory (deterministic HMAC pseudonyms) until the next run.
        return {"records": out, "entities": ents}
