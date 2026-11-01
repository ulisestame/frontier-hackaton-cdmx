"""Download every source from the sources API into a local folder, raw bytes as served.

Layout written under ``dest`` (mirrors data/fuentes/raw)::

    chats/channels.json  chats/users.json  chats/<canal>/<fecha>.json
    docs/index.json      docs/<filename>
    tables/index.json    tables/<name>
    record_index.json    tests_public.json

Everything is downloaded into a staging folder next to ``dest`` and only moved into
place once every file arrived, so a failed run never leaves a half-written ``dest``.
Names that come from the API (channels, dates, doc filenames, table names) are
sanitized with ``safe_name``; ``parse`` uses the same helpers to find the files.
"""

from __future__ import annotations

import email.utils
import json
import logging
import os
import random
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
# Top-level entries this module owns inside dest; anything else there is left alone.
MANAGED_ENTRIES = ("chats", "docs", "tables", "record_index.json", "tests_public.json")


class FetchError(RuntimeError):
    """A source could not be downloaded (after retries, when retrying made sense)."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- names


_UNSAFE_CHARS = re.compile(r"[/\\\x00-\x1f\x7f]")


def safe_name(name: object) -> str:
    """Return a single, safe path component for a name that came from the API."""
    s = _UNSAFE_CHARS.sub("_", str(name)).strip()
    s = s.lstrip(".")
    return s or "_"


def doc_local_names(index: list[dict]) -> dict[str, str]:
    """Map doc id -> file name under docs/. Deterministic; shared by fetch and parse."""
    names: dict[str, str] = {}
    used = {"index.json"}
    for entry in index:
        if not isinstance(entry, dict) or entry.get("id") is None:
            continue
        doc_id = str(entry["id"])
        if doc_id in names:
            continue
        fname = safe_name(entry.get("filename") or doc_id)
        if fname.lower() in used:  # duplicate filename (or case-insensitive clash)
            fname = safe_name(f"{doc_id}__{fname}")
        used.add(fname.lower())
        names[doc_id] = fname
    return names


def table_local_names(index: list[Any]) -> dict[str, str]:
    """Map table name (as served, e.g. 'clientes.csv') -> file name under tables/."""
    names: dict[str, str] = {}
    used = {"index.json"}
    for entry in index:
        name = entry.get("name") if isinstance(entry, dict) else entry
        if not name or str(name) in names:
            continue
        fname = safe_name(name)
        if fname.lower() in used:
            fname = safe_name(f"t{len(names)}__{fname}")
        used.add(fname.lower())
        names[str(name)] = fname
    return names


def as_list(payload: Any, *keys: str) -> list:
    """Accept either a bare JSON list or an object wrapping it under one of ``keys``."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in keys:
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


# --------------------------------------------------------------------- rate limit


class RateLimiter:
    """Thread-safe client-side limiter: a sliding 60 s window plus even spacing."""

    def __init__(self, max_per_minute: int = 500, max_per_second: float = 20.0):
        self.max_per_minute = max(1, int(max_per_minute))
        self.interval = 1.0 / max_per_second if max_per_second > 0 else 0.0
        self._starts: deque[float] = deque()
        self._next_slot = 0.0
        self._lock = threading.Lock()

    def acquire(self, abort: threading.Event | None = None) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._starts and now - self._starts[0] >= 60.0:
                    self._starts.popleft()
                if len(self._starts) >= self.max_per_minute:
                    delay = 60.0 - (now - self._starts[0]) + 0.01
                elif now < self._next_slot:
                    delay = self._next_slot - now
                else:
                    self._starts.append(now)
                    self._next_slot = now + self.interval
                    return
            if abort is not None:
                if abort.wait(delay):
                    raise FetchError("download aborted")
            else:
                time.sleep(delay)

    def pause(self, seconds: float) -> None:
        """Hold every thread back for ``seconds`` (used when the server says 429)."""
        with self._lock:
            self._next_slot = max(self._next_slot, time.monotonic() + seconds)


def _retry_after(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    return max(0.0, when.timestamp() - time.time())


# -------------------------------------------------------------------------- client


class _Fetcher:
    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        timeout: float,
        retries: int,
        limiter: RateLimiter,
        max_workers: int,
        abort: threading.Event,
        client: httpx.Client | None = None,
    ):
        self.base = base_url.rstrip("/")
        self._auth = {"Authorization": f"Bearer {token}"}
        self.retries = retries
        self.limiter = limiter
        self.abort = abort
        self._owns_client = client is None
        self.client = client or httpx.Client(
            headers={"User-Agent": "anon-sources/1.0"},
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            limits=httpx.Limits(
                max_connections=max_workers, max_keepalive_connections=max_workers
            ),
            follow_redirects=True,
        )
        self._count_lock = threading.Lock()
        self.requests = 0

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def get(
        self, path: str, *, expect_json: bool = False, headers: dict | None = None
    ) -> httpx.Response:
        """GET base/path with retries; returns the final 200 (or 304) response."""
        url = f"{self.base}/{path.lstrip('/')}"
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            if self.abort.is_set():
                raise FetchError(f"GET /{path}: download aborted")
            self.limiter.acquire(self.abort)
            with self._count_lock:
                self.requests += 1
            delay = min(30.0, 0.5 * 2**attempt) + random.uniform(0, 0.5)
            try:
                resp = self.client.get(url, headers={**self._auth, **(headers or {})})
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
            else:
                status = resp.status_code
                if status == 200 or status == 304:
                    if expect_json and status == 200:
                        try:
                            json.loads(resp.content)
                        except ValueError as exc:  # truncated or not JSON: retry
                            last = exc
                        else:
                            return resp
                    else:
                        return resp
                elif status in RETRYABLE_STATUS:
                    last = FetchError(f"HTTP {status}", status)
                    wait_s = _retry_after(resp.headers.get("Retry-After"))
                    if wait_s is not None:
                        delay = max(delay, min(wait_s, 90.0))
                    if status == 429:
                        self.limiter.pause(delay)
                else:
                    snippet = resp.text[:200].replace("\n", " ")
                    raise FetchError(f"GET /{path}: HTTP {status} {snippet!r}", status)
            if attempt < self.retries:
                log.debug("GET /%s attempt %d failed (%s); retrying in %.1fs",
                          path, attempt + 1, last, delay)
                if self.abort.wait(delay):
                    raise FetchError(f"GET /{path}: download aborted")
        status = getattr(last, "status", None)
        raise FetchError(
            f"GET /{path} failed after {self.retries + 1} attempts: "
            f"{type(last).__name__}: {last}",
            status,
        ) from last


# -------------------------------------------------------------------------- files


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:12]}.tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _move_into_place(staging: Path, dest: Path) -> None:
    """Replace the managed entries of dest with the freshly downloaded ones."""
    if not dest.exists() or (dest.is_dir() and not any(dest.iterdir())):
        if dest.exists():
            dest.rmdir()
        os.replace(staging, dest)
        return
    if not dest.is_dir():
        raise FetchError(f"{dest} exists and is not a directory")
    tag = uuid.uuid4().hex[:8]
    for name in MANAGED_ENTRIES:
        new, cur = staging / name, dest / name
        old = dest / f".{name}.old-{tag}"
        if cur.exists():
            os.replace(cur, old)
        if new.exists():
            os.replace(new, cur)
        if old.exists():
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink(missing_ok=True)
    shutil.rmtree(staging, ignore_errors=True)


# --------------------------------------------------------------------------- fetch


def _download(fetcher: _Fetcher, staging: Path, pool: ThreadPoolExecutor) -> dict:
    pending: dict[Future, tuple[str, Callable[[bytes], None] | None]] = {}
    state: dict[str, Any] = {"files": 0, "record_index_etag": None, "record_index": None}

    def task(url_path: str, rel: str | None, expect_json: bool) -> bytes:
        resp = fetcher.get(url_path, expect_json=expect_json)
        data = resp.content
        if rel is not None:
            _atomic_write(staging / rel, data)
        if url_path == "record_index":
            state["record_index_etag"] = resp.headers.get("ETag")
            state["record_index"] = data
        return data

    def submit(url_path: str, rel: str | None, *, expect_json: bool = False,
               then: Callable[[bytes], None] | None = None) -> None:
        fut = pool.submit(task, url_path, rel, expect_json)
        pending[fut] = (rel or f"/{url_path}", then)

    def on_channels(data: bytes) -> None:
        seen: set[str] = set()
        channels = as_list(json.loads(data), "channels")
        if not channels:
            log.warning("GET /chats/channels returned no channels")
        for ch in channels:
            name = ch.get("name") if isinstance(ch, dict) else ch
            if not name or name in seen:
                continue
            seen.add(name)
            submit(f"chats/{quote(str(name), safe='')}", None, expect_json=True,
                   then=lambda d, n=str(name): on_dates(n, d))

    def on_dates(channel: str, data: bytes) -> None:
        seen: set[str] = set()
        for day in as_list(json.loads(data), "dates", "days"):
            if not day or str(day) in seen:
                continue
            seen.add(str(day))
            submit(f"chats/{quote(channel, safe='')}/{quote(str(day), safe='')}",
                   f"chats/{safe_name(channel)}/{safe_name(day)}.json", expect_json=True)

    def on_docs_index(data: bytes) -> None:
        index = as_list(json.loads(data), "docs", "documents")
        if not index:
            log.warning("GET /docs returned no documents")
        for doc_id, fname in doc_local_names(index).items():
            submit(f"docs/{quote(doc_id, safe='')}", f"docs/{fname}")

    def on_tables_index(data: bytes) -> None:
        index = as_list(json.loads(data), "tables")
        if not index:
            log.warning("GET /tables returned no tables")
        for name, fname in table_local_names(index).items():
            submit(f"tables/{quote(name, safe='')}", f"tables/{fname}")

    submit("chats/channels", "chats/channels.json", expect_json=True, then=on_channels)
    submit("chats/users", "chats/users.json", expect_json=True)
    submit("docs", "docs/index.json", expect_json=True, then=on_docs_index)
    submit("tables", "tables/index.json", expect_json=True, then=on_tables_index)
    submit("record_index", "record_index.json", expect_json=True)
    submit("tests/public", "tests_public.json", expect_json=True)

    while pending:
        done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
        for fut in done:
            rel, then = pending.pop(fut)
            try:
                data = fut.result()
                if then is not None:
                    then(data)
            except Exception as exc:
                fetcher.abort.set()
                for other in pending:
                    other.cancel()
                if isinstance(exc, FetchError):
                    raise FetchError(f"could not download {rel}: {exc}", exc.status) from exc
                raise FetchError(f"could not download {rel}: {type(exc).__name__}: {exc}") from exc
            state["files"] += 1 if not rel.startswith("/") else 0
    return state


def _sources_unchanged(fetcher: _Fetcher, state: dict) -> bool:
    """Re-check record_index after the download (ETag: one cheap request)."""
    etag = state.get("record_index_etag")
    try:
        resp = fetcher.get("record_index", headers={"If-None-Match": etag} if etag else None)
    except FetchError as exc:
        log.warning("could not re-check record_index (%s); assuming unchanged", exc)
        return True
    return resp.status_code == 304 or resp.content == state.get("record_index")


def fetch_all(
    base_url: str,
    token: str,
    dest: Path,
    max_workers: int = 8,
    *,
    timeout: float = 30.0,
    retries: int = 6,
    max_per_minute: int = 500,
    max_per_second: float = 20.0,
    check_stable: bool = True,
    client: httpx.Client | None = None,
) -> Path:
    """Download every source into ``dest`` (same layout as data/fuentes/raw); return dest.

    Bounded thread pool; client-side rate limiter under the API's 600 req/min;
    retries with exponential backoff + jitter on 429/5xx/timeouts (Retry-After honored);
    every file is written atomically and the whole tree is moved into place at the end.
    If record_index changed while downloading (sources grew mid-run), it downloads once
    more so the snapshot is consistent. Raises FetchError when a file cannot be fetched.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    limiter = RateLimiter(max_per_minute=max_per_minute, max_per_second=max_per_second)
    base = base_url.rstrip("/")
    started = time.monotonic()
    for attempt in range(2):
        abort = threading.Event()
        fetcher = _Fetcher(base, token, timeout=timeout, retries=retries, limiter=limiter,
                           max_workers=max_workers, abort=abort, client=client)
        staging = Path(tempfile.mkdtemp(prefix=f".{dest.name}.partial-", dir=dest.parent))
        staging.chmod(0o755)  # mkdtemp is 0700; dest should look like a normal folder
        pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="fetch")
        try:
            try:
                fetcher.get("chats/channels", expect_json=True)
            except FetchError as exc:
                # Accept a sources URL given without the /v1 root.
                if exc.status == 404 and not base.endswith("/v1"):
                    base = f"{base}/v1"
                    fetcher.base = base
                else:
                    raise
            state = _download(fetcher, staging, pool)
            stable = not check_stable or _sources_unchanged(fetcher, state)
            if stable or attempt == 1:
                if not stable:
                    log.warning("sources changed during both downloads; keeping the last one")
                _move_into_place(staging, dest)
                log.info("fetched %d files in %.1fs (%d requests) into %s",
                         state["files"], time.monotonic() - started, fetcher.requests, dest)
                return dest
            log.warning("record_index changed while downloading; downloading again")
        finally:
            abort.set()
            pool.shutdown(wait=True, cancel_futures=True)
            fetcher.close()
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    raise AssertionError("unreachable")
