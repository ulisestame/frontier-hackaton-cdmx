"""Run the pipeline on a local raw corpus, then grade it like the judge would.

Usage:
  uv run python scripts/check_local.py sample   # data/sample/input + its 13 tests
  uv run python scripts/check_local.py real     # data/fuentes/raw + the 5 public tests

Steps: anonymize -> write output/ -> official validator (node) -> our test runner.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from anon.core.pipeline import _write_jsonl, anonymize_corpus  # noqa: E402
from anon.core.textnorm import contains, record_text  # noqa: E402
from anon.parse import load_corpus  # noqa: E402


def field_text(rec: dict, field: str | None) -> str:
    if not field or field in ("any", "raw", "*"):
        return record_text(rec)
    if field.startswith("columns."):
        return str(rec.get("columns", {}).get(field.split(".", 1)[1], ""))
    v = rec.get(field)
    return json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v


def run_tests(tests: list[dict], out: dict[str, dict], entities: list[dict]) -> list[tuple[str, bool, str]]:
    whole = "\n".join(record_text(r) for r in out.values())
    results = []
    for t in tests:
        fam, loc, payload = t["family"], t.get("locator") or {}, t.get("payload") or []
        rec = out.get(loc.get("record") or "")
        ok, why = True, ""
        if fam in ("directa",):
            hits = [p for p in payload if contains(whole, p)]
            ok, why = not hits, f"still present: {hits}"
        elif fam == "oculta":
            txt = field_text(rec, loc.get("field")) if rec else whole
            hits = [p for p in payload if contains(txt, p) or contains(whole, p)]
            ok, why = not hits, f"still present: {hits}"
        elif fam == "falso_positivo":
            txt = field_text(rec, loc.get("field")) if rec else ""
            ok, why = all(p in txt for p in payload), "kept term was modified"
        elif fam == "indirecta":
            txt = record_text(rec) if rec else ""
            ok, why = not all(contains(txt, p) for p in payload), "quasi-identifier still co-occurs"
        elif fam == "homonimos":
            names = [e["pseudonyms"].get("name") for e in entities
                     if loc.get("record") in e.get("records", []) and e.get("type") == "person"]
            ok, why = len(set(names)) >= 1, f"names {names}"
        elif fam == "consistencia":
            forms = t.get("lookup_forms") or []
            owners = [e for e in entities if any(f in e.get("originals", []) for f in forms)]
            ok = len(owners) == 1
            why = f"{len(owners)} entities own these forms"
            if ok and t.get("records"):
                name = owners[0]["pseudonyms"].get("name", "")
                missing = [r for r in t["records"] if r in out and not contains(record_text(out[r]), name)
                           and not any(contains(record_text(out[r]), v) for v in owners[0]["pseudonyms"].values())]
                ok, why = not missing, f"pseudonym missing in {missing[:3]}"
        results.append((f"{t['id']} [{fam}/{t.get('mechanism')}]", ok, "" if ok else why))
    return results


def main(which: str) -> None:
    if which == "sample":
        raw, public, tests_file = ROOT / "data/sample/input", ROOT / "data/sample", ROOT / "data/sample/tests_sample.json"
    else:
        raw, public, tests_file = ROOT / "data/fuentes/raw", ROOT / "data/fuentes/raw", ROOT / "data/fuentes/raw/tests_public.json"
    if which == "sample" and not (raw / "record_index.json").exists():
        shutil.copy(ROOT / "data/sample/record_index.json", raw / "record_index.json")
    state = Path(tempfile.mkdtemp(prefix=f"anon-state-{which}-"))
    outdir = ROOT / "output" / which
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    corpus = load_corpus(raw)
    eng, ids, chats, docs, tables, entities, leaks = anonymize_corpus(corpus, state)
    _write_jsonl(outdir / "chats.jsonl", chats)
    _write_jsonl(outdir / "docs.jsonl", docs)
    _write_jsonl(outdir / "tables.jsonl", tables)
    (outdir / "entities.json").write_text(json.dumps({"entities": entities}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"pipeline: {time.time() - t0:.1f}s  chats={len(chats)} docs={len(docs)} tables={len(tables)} "
          f"entities={len(entities)} leaks_dropped={len(leaks)} ambiguous={len(eng.warnings)}")
    for l in leaks[:15]:
        print("  leak:", l)
    v = subprocess.run(["node", str(ROOT / "material-reto/validar.mjs"), str(outdir), "--public", str(public)],
                       capture_output=True, text=True)
    print("validator:", (v.stdout + v.stderr).strip()[:3000])
    out = {r["id"]: r for r in chats + docs + tables}
    tests = json.loads(tests_file.read_text(encoding="utf-8"))
    res = run_tests(tests, out, entities)
    print(f"tests: {sum(ok for _, ok, _ in res)}/{len(res)} pass")
    for name, ok, why in res:
        print(("  PASS " if ok else "  FAIL ") + name + (f" -> {why}" if why else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample")
