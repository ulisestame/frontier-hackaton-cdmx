"""Download every source from the sources API into a local folder (raw bytes, as served).

Usage: python scripts/fetch_sources.py <out_dir>
Reads FUENTES_URL and FUENTES_TOKEN from the environment.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ["FUENTES_URL"].rstrip("/")
TOKEN = os.environ["FUENTES_TOKEN"]


def get(path: str, retries: int = 5) -> bytes:
    url = f"{BASE}/{path.lstrip('/')}"
    delay = 1.0
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError(f"unreachable: {url}")


def save(out: Path, rel: str, data: bytes) -> None:
    target = out / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def main(out_dir: str) -> None:
    out = Path(out_dir)
    channels_raw = get("chats/channels")
    save(out, "chats/channels.json", channels_raw)
    save(out, "chats/users.json", get("chats/users"))
    n_days = 0
    for ch in json.loads(channels_raw):
        name = ch["name"]
        dates = json.loads(get(f"chats/{name}"))
        if isinstance(dates, dict):
            dates = dates.get("dates", [])
        for d in dates:
            save(out, f"chats/{name}/{d}.json", get(f"chats/{name}/{d}"))
            n_days += 1
    docs_index = get("docs")
    save(out, "docs/index.json", docs_index)
    for doc in json.loads(docs_index):
        save(out, f"docs/{doc['filename']}", get(f"docs/{doc['id']}"))
    tables_index = get("tables")
    save(out, "tables/index.json", tables_index)
    tables = json.loads(tables_index)
    if isinstance(tables, dict):
        tables = tables.get("tables", [])
    for t in tables:
        name = t["name"] if isinstance(t, dict) else t
        fname = t.get("filename", name) if isinstance(t, dict) else name
        save(out, f"tables/{fname}", get(f"tables/{name}"))
    save(out, "record_index.json", get("record_index"))
    save(out, "tests_public.json", get("tests/public"))
    print(f"ok: {n_days} chat days, docs and tables saved to {out}")


if __name__ == "__main__":
    main(sys.argv[1])
