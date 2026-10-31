"""Poll the sources API and exit with a diff the moment the corpus grows.

Usage: python scripts/watch_sources.py [interval_seconds]
Reads FUENTES_URL / FUENTES_TOKEN from the environment. Writes snapshots to data/watch/.
"""

import hashlib
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = os.environ["FUENTES_URL"].rstrip("/")
TOKEN = os.environ["FUENTES_TOKEN"]
OUT = Path(__file__).resolve().parents[1] / "data" / "watch"


def get(path: str) -> bytes:
    req = urllib.request.Request(f"{BASE}/{path}", headers={"Authorization": f"Bearer {TOKEN}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def snapshot() -> dict:
    idx = json.loads(get("record_index"))
    channels = [c["name"] for c in json.loads(get("chats/channels"))]
    docs = [d["id"] for d in json.loads(get("docs"))]
    tables = {t["name"]: t.get("rows") for t in json.loads(get("tables"))}
    return {
        "at": datetime.now().isoformat(timespec="seconds"),
        "counts": {k: len(v) for k, v in idx.items()},
        "ids": {k: sorted(v) for k, v in idx.items()},
        "channels": channels,
        "docs": docs,
        "tables": tables,
        "hash": hashlib.sha256(json.dumps(idx, sort_keys=True).encode()).hexdigest()[:16],
    }


def main(interval: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    base = snapshot()
    (OUT / "baseline.json").write_text(json.dumps(base, ensure_ascii=False, indent=1))
    print(f"[{base['at']}] baseline {base['counts']} hash={base['hash']}", flush=True)
    while True:
        time.sleep(interval)
        try:
            cur = snapshot()
        except Exception as exc:  # network blips must not stop the watch
            print(f"[{datetime.now():%H:%M:%S}] poll error: {exc}", flush=True)
            continue
        if cur["hash"] != base["hash"]:
            (OUT / "after.json").write_text(json.dumps(cur, ensure_ascii=False, indent=1))
            new_ids = {k: sorted(set(cur["ids"].get(k, [])) - set(base["ids"].get(k, []))) for k in cur["ids"]}
            gone = {k: sorted(set(base["ids"].get(k, [])) - set(cur["ids"].get(k, []))) for k in base["ids"]}
            print(f"[{cur['at']}] SOURCES CHANGED {base['counts']} -> {cur['counts']}", flush=True)
            print("new channels:", sorted(set(cur["channels"]) - set(base["channels"])), flush=True)
            print("new docs:", sorted(set(cur["docs"]) - set(base["docs"])), flush=True)
            print("tables rows:", base["tables"], "->", cur["tables"], flush=True)
            print("new ids per source:", {k: len(v) for k, v in new_ids.items()}, flush=True)
            print("removed ids per source:", {k: len(v) for k, v in gone.items()}, flush=True)
            return
        print(f"[{cur['at']}] unchanged {cur['counts']}", flush=True)


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
