"""Job bookkeeping for the HTTP service: status files, output storage, runner processes.

Everything lives under STATE_DIR (env, default ./state), so a restart of the API,
or of the whole container, picks up where it left off:

    jobs/<job_id>.json          status; replaced atomically (tmp + os.replace), read without locks
    jobs/<job_id>.params.json   sources_url + token, kept for relaunches; mode 600; deleted when the job ends
    jobs/<job_id>.lock          flock held for every read-modify-write of the status file
    output/<job_id>.<n>.tmp/    attempt n of the job writes its four files here
    output/<job_id>/            the complete output, renamed from the tmp dir
    output/CURRENT              job_id of the last finished run; replaced only after the rename
    pipeline/                   the state_dir handed to run_pipeline and anonymize_live

The pipeline runs in a child process (`python -m anon.cli run ...`, see cli.py)
supervised by JobManager's monitor thread: a runner that dies without writing a
final status is relaunched (at most MAX_RELAUNCHES times), and a run that exceeds
RUN_TIMEOUT_SECONDS is killed and marked failed.

Only the standard library is imported here: the runner process loads this module
and must start fast.
"""

from __future__ import annotations

import contextlib
import fcntl
import importlib
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

OUTPUT_FILES = ("chats.jsonl", "docs.jsonl", "tables.jsonl", "entities.json")
RECORD_FILES = {"chats": "chats.jsonl", "docs": "docs.jsonl", "tables": "tables.jsonl"}
TERMINAL = frozenset({"done", "failed"})
JOB_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
DEFAULT_PIPELINE_MODULE = "anon.core.pipeline"
HISTORY_LIMIT = 20

log = logging.getLogger("anon.jobs")


# --------------------------------------------------------------------------- logging


_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()


def register_secret(value: str | None) -> None:
    """Make every log line and stored error message of this process mask `value`."""
    if value and len(value) >= 4:
        with _SECRETS_LOCK:
            _SECRETS.add(value)


def redact(text: str) -> str:
    with _SECRETS_LOCK:
        known = sorted(_SECRETS, key=len, reverse=True)
    for value in known:
        text = text.replace(value, "***")
    return text


_UNSUMMARIZED = frozenset({"exc", "traceback"})


def _summary(name: str, fields: dict, exc_text: str | None) -> str:
    """Readable one-liner for log viewers that display `message` (Railway): event key=value ..."""
    parts = [name]
    for key, value in fields.items():
        if key in _UNSUMMARIZED or value is None:
            continue
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        parts.append(f"{key}={text[:200]}{'...' if len(text) > 200 else ''}")
    exc_lines = str(exc_text or "").strip().splitlines()
    if exc_lines:
        parts.append("| " + exc_lines[-1])
    return " ".join(parts)


class JsonFormatter(logging.Formatter):
    """One JSON object per line: message (readable summary), event, level, proc, logger, ts and the fields.

    Railway parses JSON log lines and shows `message`; the other keys stay filterable attributes.
    """

    def __init__(self, proc: str) -> None:
        super().__init__()
        self.proc = proc

    def format(self, record: logging.LogRecord) -> str:
        name = record.getMessage()
        fields = getattr(record, "fields", None)
        fields = fields if isinstance(fields, dict) else {}
        exc_text = self.formatException(record.exc_info) if record.exc_info else None
        payload: dict[str, Any] = {
            "message": _summary(name, fields, exc_text or fields.get("traceback")),
            "event": name,
            "level": record.levelname.lower(),
            "ts": utc_now_iso(record.created),
            "proc": self.proc,
            "logger": record.name,
        }
        payload.update(fields)
        if exc_text:
            payload["exc"] = exc_text
        return redact(json.dumps(payload, ensure_ascii=False, default=str))


class _StdoutHandler(logging.StreamHandler):
    """Writes to whatever sys.stdout is at emit time (test capture swaps it)."""

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


def setup_logging(proc: str) -> None:
    """Route the `anon` logger hierarchy to stdout as JSON lines (idempotent)."""
    logger = logging.getLogger("anon")
    for handler in list(logger.handlers):
        if getattr(handler, "_anon_json", False):
            logger.removeHandler(handler)
    handler = _StdoutHandler()
    handler._anon_json = True  # type: ignore[attr-defined]
    handler.setFormatter(JsonFormatter(proc))
    logger.addHandler(handler)
    logger.setLevel((os.environ.get("LOG_LEVEL") or "INFO").upper())
    logger.propagate = False


def event(logger: logging.Logger, name: str, level: int = logging.INFO, exc_info: Any = None, **fields: Any) -> None:
    logger.log(level, name, extra={"fields": fields}, exc_info=exc_info)


# --------------------------------------------------------------------------- small helpers


def utc_now_iso(ts: float | None = None) -> str:
    moment = datetime.fromtimestamp(time.time() if ts is None else ts, tz=UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def parse_iso(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def new_job_id() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(3)


def _env_number(name: str, default: float, cast: Callable[[str], Any]) -> Any:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return cast(raw)
    except ValueError:
        event(log, "config.invalid", logging.WARNING, variable=name, value=raw, using=default)
        return default


def env_float(name: str, default: float) -> float:
    return _env_number(name, default, float)


def env_int(name: str, default: int) -> int:
    return _env_number(name, default, int)


def pipeline_module_name() -> str:
    return os.environ.get("ANON_PIPELINE_MODULE", "").strip() or DEFAULT_PIPELINE_MODULE


def load_pipeline(attr: str) -> Callable[..., Any]:
    """Return run_pipeline / anonymize_live, resolved at call time (tests point ANON_PIPELINE_MODULE at a fake)."""
    return getattr(importlib.import_module(pipeline_module_name()), attr)


@dataclass(frozen=True)
class Settings:
    run_timeout: float = 115 * 60.0
    max_relaunches: int = 2
    keep_outputs: int = 3
    monitor_interval: float = 2.0

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            run_timeout=env_float("RUN_TIMEOUT_SECONDS", cls.run_timeout),
            max_relaunches=max(0, env_int("MAX_RELAUNCHES", cls.max_relaunches)),
            keep_outputs=max(1, env_int("OUTPUT_KEEP", cls.keep_outputs)),
            monitor_interval=max(0.01, env_float("MONITOR_INTERVAL_SECONDS", cls.monitor_interval)),
        )


# --------------------------------------------------------------------------- layout and file IO


@dataclass(frozen=True)
class Layout:
    root: Path

    @classmethod
    def from_env(cls, state_dir: str | os.PathLike[str] | None = None) -> Layout:
        raw = state_dir or os.environ.get("STATE_DIR") or "state"
        return cls(Path(raw).expanduser().resolve())

    @property
    def jobs(self) -> Path:
        return self.root / "jobs"

    @property
    def output(self) -> Path:
        return self.root / "output"

    @property
    def pipeline(self) -> Path:
        return self.root / "pipeline"

    @property
    def current_file(self) -> Path:
        return self.output / "CURRENT"

    def status_path(self, job_id: str) -> Path:
        return self.jobs / f"{job_id}.json"

    def params_path(self, job_id: str) -> Path:
        return self.jobs / f"{job_id}.params.json"

    def lock_path(self, job_id: str) -> Path:
        return self.jobs / f"{job_id}.lock"

    def tmp_output(self, job_id: str, attempt: int) -> Path:
        return self.output / f"{job_id}.{attempt}.tmp"

    def final_output(self, job_id: str) -> Path:
        return self.output / job_id

    def ensure(self) -> None:
        self.jobs.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.jobs, 0o700)
        self.output.mkdir(parents=True, exist_ok=True)
        self.pipeline.mkdir(parents=True, exist_ok=True)


def _fsync_path(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes, mode: int = 0o644) -> None:
    """Write via a sibling temp file + os.replace, so readers see the old or the new file, never half."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with contextlib.suppress(FileNotFoundError):
        os.unlink(tmp)
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(fd, "wb") as fh:
            os.fchmod(fh.fileno(), mode)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def write_json(path: Path, obj: Any, mode: int = 0o644) -> None:
    atomic_write_bytes(path, json.dumps(obj, ensure_ascii=False, indent=1, default=str).encode("utf-8"), mode)


def read_json(path: Path) -> Any:
    """Parsed JSON, or None if the file does not exist. Invalid JSON raises ValueError."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None


@contextlib.contextmanager
def job_lock(layout: Layout, job_id: str, timeout: float = 30.0) -> Iterator[None]:
    """Exclusive flock shared by the API and the runner. Never nest it: flock does not re-enter."""
    fd = os.open(layout.lock_path(job_id), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"could not lock job {job_id} within {timeout:g}s") from None
                time.sleep(0.01)
        yield
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- status files


def read_status(layout: Layout, job_id: str) -> dict | None:
    if not JOB_ID_RE.match(job_id or ""):
        return None
    data = read_json(layout.status_path(job_id))
    return data if isinstance(data, dict) else None


def write_status(layout: Layout, status: dict) -> None:
    """Write a status dict. Callers doing read-modify-write must hold job_lock (see update_status)."""
    status["updated_at"] = utc_now_iso()
    write_json(layout.status_path(status["job_id"]), status)


def update_status(
    layout: Layout, job_id: str, mutate: Callable[[dict], bool | None], *, lock_timeout: float = 30.0
) -> tuple[dict | None, bool]:
    """Locked read-modify-write. `mutate` edits the dict in place; returning False skips the write.

    Returns (status, written). Exceptions raised by `mutate` propagate, with nothing written.
    """
    with job_lock(layout, job_id, lock_timeout):
        status = read_status(layout, job_id)
        if status is None:
            return None, False
        if mutate(status) is False:
            return status, False
        write_status(layout, status)
        return status, True


def add_history(status: dict, name: str, detail: str) -> None:
    history = status.setdefault("history", [])
    history.append({"at": utc_now_iso(), "event": name, "detail": detail})
    del history[:-HISTORY_LIMIT]


def elapsed_seconds(status: dict, now: float | None = None) -> float:
    started = parse_iso(status.get("started_at") or status.get("created_at"))
    if started is None:
        return 0.0
    return max(0.0, (time.time() if now is None else now) - started)


def public_status(status: dict, now: float | None = None) -> dict:
    """GET /run/{job_id} body. Optional fields are omitted rather than null, as the contract types them as strings."""
    state = status.get("status") or "queued"
    records = status.get("records") or {}
    cost = status.get("cost") or {}
    if state in TERMINAL:
        seconds = float(cost.get("seconds") or 0.0)
    else:
        seconds = elapsed_seconds(status, now)
    body: dict[str, Any] = {
        "job_id": status.get("job_id"),
        "status": state,
        "started_at": status.get("started_at") or status.get("created_at"),
        "records": {name: as_int(records.get(name)) for name in RECORD_FILES},
        "cost": {
            "tokens_in": as_int(cost.get("tokens_in")),
            "tokens_out": as_int(cost.get("tokens_out")),
            "seconds": round(seconds, 3),
        },
    }
    if status.get("finished_at"):
        body["finished_at"] = status["finished_at"]
    if state == "failed":
        body["error"] = str(status.get("error") or "failed")
    if status.get("progress") is not None:
        body["progress"] = status["progress"]
    body["relaunches"] = max(0, as_int(status.get("attempt")) - 1)
    return body


# --------------------------------------------------------------------------- output storage


def current_job_id(layout: Layout) -> str | None:
    try:
        job_id = layout.current_file.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError):
        return None
    if JOB_ID_RE.match(job_id) and layout.final_output(job_id).is_dir():
        return job_id
    return None


def current_output_dir(layout: Layout) -> Path | None:
    """Folder of the last finished run (what GET /output serves), or None before the first one."""
    job_id = current_job_id(layout)
    return layout.final_output(job_id) if job_id else None


def output_file(layout: Layout, name: str) -> Path | None:
    if name not in OUTPUT_FILES:
        return None
    folder = current_output_dir(layout)
    if folder is None:
        return None
    path = folder / name
    return path if path.is_file() else None


def check_output(folder: Path) -> list[str]:
    """Problems that would make a finished run unservable; empty when all four files are usable."""
    problems = [f"missing {name}" for name in OUTPUT_FILES if not (folder / name).is_file()]
    entities = folder / "entities.json"
    if entities.is_file():
        try:
            data = json.loads(entities.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            problems.append(f"entities.json is not valid JSON ({exc})")
        else:
            if not isinstance(data, dict) or not isinstance(data.get("entities"), list):
                problems.append('entities.json must be an object with an "entities" list')
    return problems


def count_lines(path: Path) -> int:
    count = 0
    try:
        with path.open("rb") as fh:
            for line in fh:
                if line.strip():
                    count += 1
    except FileNotFoundError:
        return 0
    return count


def count_records(folder: Path) -> dict[str, int]:
    return {source: count_lines(folder / name) for source, name in RECORD_FILES.items()}


def promote_output(layout: Layout, job_id: str, tmp_dir: Path) -> Path:
    """Rename tmp_dir to output/<job_id>/, then point CURRENT at it. Caller holds the job lock."""
    for name in OUTPUT_FILES:
        _fsync_path(tmp_dir / name)
    _fsync_path(tmp_dir)
    final = layout.final_output(job_id)
    if final.exists():
        shutil.rmtree(final)
    os.replace(tmp_dir, final)
    os.utime(final)
    atomic_write_bytes(layout.current_file, (job_id + "\n").encode("utf-8"))
    _fsync_path(layout.output)
    return final


def prune_outputs(layout: Layout, keep: int) -> list[str]:
    """Delete finished outputs beyond the newest `keep`; CURRENT is always kept. Never touches .tmp dirs."""
    if not layout.output.is_dir():
        return []
    current = current_job_id(layout)
    finished = []
    for entry in layout.output.iterdir():
        if entry.is_dir() and not entry.name.endswith(".tmp") and JOB_ID_RE.match(entry.name):
            with contextlib.suppress(FileNotFoundError):
                finished.append((entry.stat().st_mtime, entry))
    finished.sort(key=lambda item: item[0], reverse=True)
    keepers = {entry.name for _, entry in finished[: max(1, keep)]}
    if current:
        keepers.add(current)
    removed = []
    for _, entry in finished:
        if entry.name not in keepers:
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
    return removed


# --------------------------------------------------------------------------- runner processes


def _arg_after(args: list[str], flag: str) -> str | None:
    try:
        return args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return None


def _is_runner(args: list[str], job_id: str) -> bool:
    return "anon.cli" in args and "run" in args and _arg_after(args, "--job-id") == job_id


_HAS_PROC = Path("/proc/self/cmdline").exists()


def _proc_args(pid: int) -> list[str] | None:
    """Linux: argv of a live, non-zombie process, or None."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    state = stat[stat.rfind(")") + 2 : stat.rfind(")") + 3]
    if not raw or state in ("Z", "X"):
        return None
    return [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]


def runner_pids(job_id: str) -> list[int]:
    """PIDs of live runner processes for job_id, identified by their command line (survives PID reuse)."""
    me = os.getpid()
    found: list[int] = []
    if _HAS_PROC:
        for entry in os.scandir("/proc"):
            if entry.name.isdigit() and int(entry.name) != me:
                args = _proc_args(int(entry.name))
                if args and _is_runner(args, job_id):
                    found.append(int(entry.name))
        return found
    try:
        result = subprocess.run(
            ["ps", "-axww", "-o", "pid=,stat=,command="], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return found
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if (len(parts) == 3 and parts[0].isdigit() and int(parts[0]) != me and not parts[1].startswith("Z")
                and _is_runner(parts[2].split(), job_id)):
            found.append(int(parts[0]))
    return found


def pid_is_runner(pid: int, job_id: str) -> bool:
    if _HAS_PROC:
        args = _proc_args(pid)
        return bool(args) and _is_runner(args, job_id)
    try:
        result = subprocess.run(
            ["ps", "-ww", "-o", "stat=,command=", "-p", str(pid)], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return False
    parts = result.stdout.strip().split(None, 1)
    return len(parts) == 2 and not parts[0].startswith("Z") and _is_runner(parts[1].split(), job_id)


class RunnerHandle:
    """A runner the API launched (owns the Popen) or adopted after a restart (pid only)."""

    def __init__(self, job_id: str, pid: int, proc: subprocess.Popen | None = None) -> None:
        self.job_id = job_id
        self.pid = pid
        self.proc = proc

    @property
    def adopted(self) -> bool:
        return self.proc is None

    def poll(self) -> int | None:
        """None while alive; the exit code once gone (-1 when unknown, for adopted runners)."""
        if self.proc is not None:
            return self.proc.poll()
        return None if pid_is_runner(self.pid, self.job_id) else -1

    def describe_exit(self, code: int) -> str:
        if self.adopted:
            return "exit status unknown"
        return f"signal {-code}" if code < 0 else f"exit code {code}"

    def signal_group(self, sig: int) -> None:
        """Signal the runner's whole process group (it is a session leader), pipeline subprocesses included."""
        try:
            os.killpg(self.pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            with contextlib.suppress(OSError):
                os.kill(self.pid, sig)

    def kill(self, grace: float = 0.0) -> None:
        if self.adopted and self.poll() is not None:
            return  # gone, and its pid may already belong to someone else
        if grace > 0 and self.poll() is None:
            self.signal_group(signal.SIGTERM)
            deadline = time.monotonic() + grace
            while time.monotonic() < deadline and self.poll() is None:
                time.sleep(0.05)
        self.signal_group(signal.SIGKILL)
        if self.proc is not None:
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=5)


class SubprocessLauncher:
    """Starts `python -m anon.cli run` in its own session. The token travels in the environment, never in argv."""

    def __init__(self, python: str | None = None) -> None:
        self.python = python or sys.executable

    def launch(self, layout: Layout, job_id: str, attempt: int, params: dict) -> RunnerHandle:
        env = dict(os.environ)
        env["SOURCES_URL"] = str(params["sources_url"])
        env["SOURCES_TOKEN"] = str(params["token"])
        env["PYTHONUNBUFFERED"] = "1"
        package_root = str(Path(__file__).resolve().parent.parent)
        env["PYTHONPATH"] = package_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        cmd = [
            self.python, "-m", "anon.cli", "run",
            "--job-id", job_id, "--state-dir", str(layout.root), "--attempt", str(attempt),
        ]
        # stdout/stderr are inherited (container logs); a pipe would break the runner if the API restarted.
        proc = subprocess.Popen(cmd, env=env, stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return RunnerHandle(job_id, proc.pid, proc)


# --------------------------------------------------------------------------- the manager


@dataclass
class _Active:
    job_id: str
    attempt: int = 0
    handle: RunnerHandle | None = None


class JobManager:
    """Owns the single active job: POST /run idempotency, crash recovery, relaunches and the watchdog."""

    def __init__(self, layout: Layout, settings: Settings | None = None, launcher: Any = None) -> None:
        self.layout = layout
        self.settings = settings or Settings.from_env()
        self.launcher = launcher or SubprocessLauncher()
        self._lock = threading.RLock()
        self._active: _Active | None = None
        self._exited: list[RunnerHandle] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- lifecycle

    def startup(self) -> None:
        self.layout.ensure()
        for step in (self.recover, self.cleanup):
            try:
                step()
            except Exception:
                event(log, "jobs.startup_step_failed", logging.ERROR, exc_info=True, step=step.__name__)
        self._stop.clear()
        self._thread = threading.Thread(target=self._monitor_loop, name="job-monitor", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            active = self._active
            if active and active.handle and active.handle.poll() is None:
                event(log, "job.interrupted", logging.WARNING, job_id=active.job_id,
                      detail="service stopping; the run is relaunched on the next start")
                active.handle.kill(grace=2.0)

    # ---- API entry points

    def submit(self, sources_url: str, token: str) -> tuple[str, bool]:
        """Start a run, or return the one already queued/running. Returns (job_id, created)."""
        register_secret(token)
        with self._lock:
            if self._active is not None:
                status = read_status(self.layout, self._active.job_id)
                if status is not None and status.get("status") not in TERMINAL:
                    return self._active.job_id, False
                self._finish_locked(self._active.job_id, status)
            self.layout.ensure()  # cheap; survives a state dir removed under a running server
            job_id = new_job_id()
            now = utc_now_iso()
            params = {"job_id": job_id, "sources_url": sources_url, "token": token, "created_at": now}
            write_json(self.layout.params_path(job_id), params, mode=0o600)
            write_json(self.layout.status_path(job_id), {
                "job_id": job_id,
                "status": "queued",
                "created_at": now,
                "started_at": now,
                "records": {name: 0 for name in RECORD_FILES},
                "cost": {"tokens_in": 0, "tokens_out": 0, "seconds": 0.0},
                "attempt": 0,
                "sources_url": redact(sources_url),
                "history": [],
                "updated_at": now,
            })
            self._active = _Active(job_id)
            event(log, "job.created", job_id=job_id, sources_url=redact(sources_url))
            self._launch_locked(job_id, "POST /run")
            return job_id, True

    def get(self, job_id: str) -> dict | None:
        return read_status(self.layout, job_id)

    def active_job_id(self) -> str | None:
        with self._lock:
            return self._active.job_id if self._active else None

    # ---- recovery and housekeeping

    def recover(self) -> None:
        """At startup: adopt a runner that is still alive, relaunch one that is gone, or give up on it."""
        pending = []
        for path in self.layout.jobs.glob("*.json"):
            if path.name.startswith(".") or path.name.endswith(".params.json"):
                continue
            try:
                status = read_json(path)
            except ValueError:
                event(log, "job.status_unreadable", logging.ERROR, path=str(path))
                continue
            if (isinstance(status, dict) and status.get("status") not in TERMINAL
                    and JOB_ID_RE.match(str(status.get("job_id", "")))):
                pending.append(status)
        if not pending:
            return
        pending.sort(key=lambda item: str(item.get("created_at") or ""))
        newest = pending[-1]
        with self._lock:
            for older in pending[:-1]:
                self._kill_runners(older["job_id"])
                self._fail_locked(older["job_id"], f"abandoned: superseded by {newest['job_id']}")
            job_id = newest["job_id"]
            attempt = as_int(newest.get("attempt"))
            self._active = _Active(job_id, attempt)
            if elapsed_seconds(newest) > self.settings.run_timeout:
                self._kill_runners(job_id)
                self._fail_locked(job_id, "timeout")
                return
            pids = runner_pids(job_id)
            if pids:
                self._active.handle = RunnerHandle(job_id, pids[0])
                event(log, "job.adopted", job_id=job_id, pid=pids[0], attempt=attempt)
                return
            if attempt >= 1 + self.settings.max_relaunches:
                self._fail_locked(job_id, self._limit_error(attempt, "the service restarted and the runner was gone"))
                return
            reason = "service restarted and the runner was gone" if attempt else "service restarted before launch"
            event(log, "job.recovering", logging.WARNING, job_id=job_id, attempt=attempt, reason=reason)
            self._launch_locked(job_id, reason)

    def cleanup(self) -> None:
        """Drop params of finished jobs, leftover tmp dirs and outputs beyond the retention limit."""
        with self._lock:
            active = (self._active.job_id, self._active.attempt) if self._active else None
        for path in self.layout.jobs.glob("*.params.json"):
            job_id = path.name[: -len(".params.json")]
            status = read_status(self.layout, job_id)
            if status is None or status.get("status") in TERMINAL:
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
        for entry in self.layout.output.glob("*.tmp"):
            if entry.is_dir() and (not active or entry.name != self.layout.tmp_output(*active).name):
                shutil.rmtree(entry, ignore_errors=True)
        removed = prune_outputs(self.layout, self.settings.keep_outputs)
        if removed:
            event(log, "output.pruned", removed=removed)

    # ---- monitor thread

    def _monitor_loop(self) -> None:
        while not self._stop.wait(self.settings.monitor_interval):
            try:
                self._tick()
            except Exception:
                event(log, "jobs.monitor_error", logging.ERROR, exc_info=True)

    def _tick(self) -> None:
        with self._lock:
            self._exited = [handle for handle in self._exited if handle.poll() is None]  # reaps zombies
            active = self._active
            if active is None:
                return
            job_id = active.job_id
            status = read_status(self.layout, job_id)
            if status is None:
                event(log, "job.status_missing", logging.ERROR, job_id=job_id)
                self._active = None
                return
            if status.get("status") in TERMINAL:
                self._finish_locked(job_id, status)
                return
            if elapsed_seconds(status) > self.settings.run_timeout:
                self._fail_locked(job_id, "timeout")
                return
            if active.handle is None:
                self._launch_locked(job_id, "runner not started")
                return
            code = active.handle.poll()
            if code is None:
                return
            status = read_status(self.layout, job_id)
            if status is None or status.get("status") in TERMINAL:
                self._finish_locked(job_id, status)
                return
            self._runner_died_locked(status, active.handle, code)

    # ---- internals (all called with self._lock held)

    def _limit_error(self, attempt: int, last: str) -> str:
        return (f"pipeline process died unexpectedly on {attempt} attempt(s) (last: {last}); "
                f"relaunch limit of {self.settings.max_relaunches} reached")

    def _runner_died_locked(self, status: dict, handle: RunnerHandle, code: int) -> None:
        job_id = status["job_id"]
        attempt = as_int(status.get("attempt")) or 1
        how = handle.describe_exit(code)
        if not handle.adopted:
            handle.signal_group(signal.SIGKILL)  # leftover pipeline subprocesses of the dead runner
        event(log, "job.runner_died", logging.WARNING, job_id=job_id, attempt=attempt, exit=how)
        if attempt < 1 + self.settings.max_relaunches:
            self._launch_locked(job_id, f"runner died before finishing ({how})")
        else:
            self._fail_locked(job_id, self._limit_error(attempt, how), kill=False)

    def _launch_locked(self, job_id: str, reason: str) -> None:
        try:
            params = read_json(self.layout.params_path(job_id))
        except ValueError:
            params = None
        if not isinstance(params, dict) or not params.get("sources_url") or "token" not in params:
            self._fail_locked(job_id, "cannot launch the pipeline: the run parameters are missing", kill=False)
            return
        bumped: dict[str, int] = {}

        def bump(status: dict) -> bool | None:
            if status.get("status") in TERMINAL:
                return False
            status["attempt"] = as_int(status.get("attempt")) + 1
            status["launched_at"] = utc_now_iso()
            status.pop("pid", None)
            add_history(status, "launch", f"attempt {status['attempt']}: {reason}")
            bumped["attempt"] = status["attempt"]
            return None

        try:
            status, written = update_status(self.layout, job_id, bump, lock_timeout=10)
        except TimeoutError:
            event(log, "job.lock_timeout", logging.WARNING, job_id=job_id, during="launch")
            return  # retried on the next tick
        if not written:
            self._finish_locked(job_id, status)
            return
        attempt = bumped["attempt"]
        for previous in range(1, attempt):
            shutil.rmtree(self.layout.tmp_output(job_id, previous), ignore_errors=True)
        try:
            handle = self.launcher.launch(self.layout, job_id, attempt, params)
        except Exception as exc:
            event(log, "job.launch_failed", logging.ERROR, exc_info=True, job_id=job_id, attempt=attempt)
            self._fail_locked(job_id, redact(f"could not start the pipeline process: {type(exc).__name__}: {exc}"),
                              kill=False)
            return
        self._active = _Active(job_id, attempt, handle)

        def record_pid(status: dict) -> bool | None:
            if status.get("status") in TERMINAL or as_int(status.get("attempt")) != attempt:
                return False
            status["pid"] = handle.pid
            return None

        with contextlib.suppress(TimeoutError):
            update_status(self.layout, job_id, record_pid, lock_timeout=10)
        event(log, "job.launched", job_id=job_id, attempt=attempt, pid=handle.pid, reason=reason)

    def _fail_locked(self, job_id: str, error: str, kill: bool = True) -> bool:
        def mark(status: dict) -> bool | None:
            if status.get("status") in TERMINAL:
                return False
            status["status"] = "failed"
            status["error"] = error
            status["finished_at"] = utc_now_iso()
            status.setdefault("cost", {})["seconds"] = round(elapsed_seconds(status), 3)
            add_history(status, "failed", error)
            return None

        try:
            status, written = update_status(self.layout, job_id, mark, lock_timeout=10)
        except TimeoutError:
            event(log, "job.lock_timeout", logging.WARNING, job_id=job_id, during="fail")
            return False  # retried on the next tick
        if written:
            event(log, "job.failed", logging.WARNING, job_id=job_id, error=error)
            active = self._active
            if kill and active and active.job_id == job_id and active.handle:
                active.handle.kill()
        self._finish_locked(job_id, status)
        return written

    def _finish_locked(self, job_id: str, status: dict | None) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.layout.params_path(job_id).unlink()
        active = self._active
        if active and active.job_id == job_id:
            if active.handle is not None:
                self._exited.append(active.handle)
            self._active = None
            if status is not None:
                event(log, "job.finished", job_id=job_id, status=status.get("status"),
                      records=status.get("records"), seconds=(status.get("cost") or {}).get("seconds"),
                      attempts=status.get("attempt"), error=status.get("error"))

    def _kill_runners(self, job_id: str) -> None:
        for pid in runner_pids(job_id):
            RunnerHandle(job_id, pid).kill()
