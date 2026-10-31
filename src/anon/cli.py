"""Command line entry points.

    python -m anon.cli run --job-id ID --state-dir DIR [--attempt N]
        One attempt of a job, spawned by the API (jobs.SubprocessLauncher). Reads SOURCES_URL and
        SOURCES_TOKEN from the environment (never argv), lets run_pipeline write into
        output/<job>.<attempt>.tmp/, promotes that folder and marks the job done, or marks it
        failed with the error message (token masked).

    python -m anon.cli once --sources-url URL --out DIR [--state-dir DIR]
        Run the pipeline once into a local folder; the token comes from FUENTES_TOKEN.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import shutil
import sys
import threading
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from anon import jobs

log = logging.getLogger("anon.cli")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_NOT_MINE = 3
PROGRESS_MAX_CHARS = 4000
ERROR_MAX_CHARS = 1000


class NotMine(Exception):
    """The job already finished or moved on to another attempt: this runner stops without writing."""


class IncompleteOutput(RuntimeError):
    pass


def _owned(status: dict, attempt: int) -> None:
    if status.get("status") in jobs.TERMINAL:
        raise NotMine(f"job already {status.get('status')}")
    if jobs.as_int(status.get("attempt")) != attempt:
        raise NotMine(f"attempt {attempt} was superseded by attempt {status.get('attempt')}")


def _payload(event: Any, fields: dict) -> dict:
    """A progress event as plain JSON: token masked, size capped."""
    if isinstance(event, dict):
        raw = {**event, **fields}
    elif event is None:
        raw = dict(fields)
    else:
        raw = {"message": str(event), **fields}
    try:
        text = jobs.redact(json.dumps(raw, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        text = json.dumps({"message": jobs.redact(str(raw))}, ensure_ascii=False)
    if len(text) > PROGRESS_MAX_CHARS:
        return {"truncated": True, "keys": sorted(str(key) for key in raw)[:50]}
    return json.loads(text)


def _tokens(result: Any, fallback: dict) -> tuple[int, int]:
    tokens_in, tokens_out = fallback.get("tokens_in"), fallback.get("tokens_out")
    if isinstance(result, dict):
        tokens_in = result.get("tokens_in", tokens_in)
        tokens_out = result.get("tokens_out", tokens_out)
    return jobs.as_int(tokens_in), jobs.as_int(tokens_out)


def _hard_exit(code: int) -> None:
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.flush()
    os._exit(code)


class ProgressReporter:
    """The `progress` callback handed to run_pipeline.

    Thread-safe and throttled (one status write per second, or on a new "stage"); it never
    raises into the pipeline. Keys "records" ({chats, docs, tables}) and "tokens_in"/"tokens_out"
    are mirrored into the job status so GET /run shows them live.
    """

    def __init__(self, layout: jobs.Layout, job_id: str, attempt: int, min_interval: float = 1.0) -> None:
        self.layout = layout
        self.job_id = job_id
        self.attempt = attempt
        self.min_interval = min_interval
        self.last: dict | None = None
        self._mutex = threading.Lock()
        self._last_write = 0.0
        self._last_stage: Any = object()

    def __call__(self, event: Any = None, **fields: Any) -> None:
        try:
            payload = _payload(event, fields)
            with self._mutex:
                self.last = payload
                now = time.monotonic()
                stage = payload.get("stage")
                since = now - self._last_write
                if since < self.min_interval and (stage == self._last_stage or since < 0.1):
                    return
                self._last_write = now
                self._last_stage = stage
                jobs.update_status(self.layout, self.job_id, self._apply, lock_timeout=5.0)
        except NotMine as exc:
            jobs.event(log, "runner.superseded", logging.WARNING, job_id=self.job_id, detail=str(exc))
            _hard_exit(EXIT_NOT_MINE)
        except Exception as exc:
            jobs.event(log, "runner.progress_failed", logging.WARNING, job_id=self.job_id, error=jobs.redact(repr(exc)))

    def _apply(self, status: dict) -> None:
        _owned(status, self.attempt)
        payload = self.last or {}
        status["progress"] = payload
        records = payload.get("records")
        if isinstance(records, dict):
            current = status.setdefault("records", {})
            for name in jobs.RECORD_FILES:
                if name in records:
                    current[name] = jobs.as_int(records[name])
        cost = status.setdefault("cost", {})
        for key in ("tokens_in", "tokens_out"):
            if key in payload:
                cost[key] = jobs.as_int(payload[key])


def run_job(
    layout: jobs.Layout,
    job_id: str,
    attempt: int | None,
    sources_url: str,
    token: str,
    *,
    pipeline_fn: Callable[..., Any] | None = None,
    keep_outputs: int | None = None,
) -> int:
    """Run one attempt of `job_id`. Returns the process exit code (see EXIT_*)."""
    jobs.register_secret(token)
    layout.ensure()
    started = time.monotonic()
    claimed: dict[str, int] = {}

    def claim(status: dict) -> None:
        if status.get("status") in jobs.TERMINAL:
            raise NotMine(f"job already {status.get('status')}")
        current = jobs.as_int(status.get("attempt"))
        if attempt is None:  # manual invocation: take over the current attempt
            mine = status["attempt"] = max(1, current)
        elif current != attempt:
            raise NotMine(f"attempt {attempt} was superseded by attempt {current}")
        else:
            mine = attempt
        claimed["attempt"] = mine
        status["status"] = "running"
        status["pid"] = os.getpid()
        status["attempt_started_at"] = jobs.utc_now_iso()
        status.setdefault("started_at", status.get("created_at") or jobs.utc_now_iso())
        jobs.add_history(status, "running", f"attempt {mine}, pid {os.getpid()}")

    try:
        status, _ = jobs.update_status(layout, job_id, claim)
    except NotMine as exc:
        jobs.event(log, "runner.not_started", logging.WARNING, job_id=job_id, detail=str(exc))
        return EXIT_NOT_MINE
    except TimeoutError as exc:
        jobs.event(log, "runner.not_started", logging.ERROR, job_id=job_id, detail=str(exc))
        return EXIT_FAILED  # the API sees a runner that died before finishing and relaunches it
    if status is None:
        jobs.event(log, "runner.unknown_job", logging.ERROR, job_id=job_id, state_dir=str(layout.root))
        return EXIT_USAGE

    mine = claimed["attempt"]
    tmp = layout.tmp_output(job_id, mine)
    reporter = ProgressReporter(layout, job_id, mine)
    jobs.event(log, "runner.started", job_id=job_id, attempt=mine, pid=os.getpid(),
               sources_url=jobs.redact(sources_url), out_dir=str(tmp))
    try:
        if not sources_url or not token:
            raise RuntimeError("SOURCES_URL and SOURCES_TOKEN must be set in the runner environment")
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True)
        run_pipeline = pipeline_fn or jobs.load_pipeline("run_pipeline")
        result = run_pipeline(sources_url, token, tmp, layout.pipeline, reporter)
        problems = jobs.check_output(tmp)
        if problems:
            raise IncompleteOutput("pipeline output incomplete: " + "; ".join(problems))
        records = jobs.count_records(tmp)
        _warn_on_count_mismatch(job_id, result, records)
        code = _finish_done(layout, job_id, mine, tmp, records, result, reporter, started)
    except BaseException as exc:  # noqa: BLE001 - a crashed pipeline must still end as "failed"
        code = _finish_failed(layout, job_id, mine, tmp, exc, reporter, started)
    if code == EXIT_NOT_MINE:
        return code  # the params file now belongs to whoever owns the job
    with contextlib.suppress(FileNotFoundError):
        layout.params_path(job_id).unlink()
    if code == EXIT_OK:
        keep = keep_outputs or jobs.Settings.from_env().keep_outputs
        try:
            removed = jobs.prune_outputs(layout, keep)
        except OSError as exc:
            jobs.event(log, "output.prune_failed", logging.WARNING, error=repr(exc))
        else:
            if removed:
                jobs.event(log, "output.pruned", removed=removed)
    return code


def _warn_on_count_mismatch(job_id: str, result: Any, records: dict[str, int]) -> None:
    reported = result.get("records") if isinstance(result, dict) else None
    if not isinstance(reported, dict):
        return
    diff = {name: {"reported": jobs.as_int(reported[name]), "lines": records[name]}
            for name in records if name in reported and jobs.as_int(reported[name]) != records[name]}
    if diff:
        jobs.event(log, "runner.count_mismatch", logging.WARNING, job_id=job_id, counts=diff,
                   detail="status reports the line counts of the files")


def _finish_done(layout: jobs.Layout, job_id: str, attempt: int, tmp: Path, records: dict[str, int],
                 result: Any, reporter: ProgressReporter, started: float) -> int:
    # Promotion and the "done" write happen under the job lock, so the API's watchdog can never
    # mark the job failed in between, and an outdated attempt can never promote its output.
    with jobs.job_lock(layout, job_id):
        status = jobs.read_status(layout, job_id)
        try:
            if status is None:
                raise NotMine("status file vanished")
            _owned(status, attempt)
        except NotMine as exc:
            jobs.event(log, "runner.not_promoted", logging.WARNING, job_id=job_id, detail=str(exc))
            shutil.rmtree(tmp, ignore_errors=True)
            return EXIT_NOT_MINE
        jobs.promote_output(layout, job_id, tmp)
        now = time.time()
        tokens_in, tokens_out = _tokens(result, status.get("cost") or {})
        status["status"] = "done"
        status["finished_at"] = jobs.utc_now_iso(now)
        status["records"] = records
        status["cost"] = {"tokens_in": tokens_in, "tokens_out": tokens_out,
                          "seconds": round(jobs.elapsed_seconds(status, now), 3)}
        status["attempt_seconds"] = round(time.monotonic() - started, 3)
        if reporter.last is not None:
            status["progress"] = reporter.last
        status.pop("error", None)
        jobs.add_history(status, "done", f"attempt {attempt}")
        jobs.write_status(layout, status)
    jobs.event(log, "runner.done", job_id=job_id, attempt=attempt, records=records,
               tokens_in=tokens_in, tokens_out=tokens_out, seconds=status["cost"]["seconds"])
    return EXIT_OK


def _finish_failed(layout: jobs.Layout, job_id: str, attempt: int, tmp: Path, exc: BaseException,
                   reporter: ProgressReporter, started: float) -> int:
    error = jobs.redact(f"{type(exc).__name__}: {exc}").strip()
    if len(error) > ERROR_MAX_CHARS:
        error = error[:ERROR_MAX_CHARS] + "..."
    jobs.event(log, "runner.failed", logging.ERROR, job_id=job_id, attempt=attempt, error=error,
               traceback=jobs.redact("".join(traceback.format_exception(exc))))
    shutil.rmtree(tmp, ignore_errors=True)

    def mark(status: dict) -> None:
        _owned(status, attempt)
        now = time.time()
        status["status"] = "failed"
        status["error"] = error
        status["finished_at"] = jobs.utc_now_iso(now)
        status.setdefault("cost", {})["seconds"] = round(jobs.elapsed_seconds(status, now), 3)
        status["attempt_seconds"] = round(time.monotonic() - started, 3)
        if reporter.last is not None:
            status["progress"] = reporter.last
        jobs.add_history(status, "failed", error)

    try:
        jobs.update_status(layout, job_id, mark)
    except NotMine as not_mine:
        jobs.event(log, "runner.not_marked", logging.WARNING, job_id=job_id, detail=str(not_mine))
        return EXIT_NOT_MINE
    except Exception:
        jobs.event(log, "runner.status_write_failed", logging.ERROR, exc_info=True, job_id=job_id)
    return EXIT_FAILED


def _deprioritize() -> None:
    """Under memory or CPU pressure the runner loses to the API, which must keep answering."""
    with contextlib.suppress(OSError):
        Path("/proc/self/oom_score_adj").write_text("500")
    with contextlib.suppress(OSError, AttributeError):
        os.nice(5)


def cmd_run(args: argparse.Namespace) -> int:
    jobs.setup_logging("runner")
    if not jobs.JOB_ID_RE.match(args.job_id):
        jobs.event(log, "runner.bad_job_id", logging.ERROR, job_id=args.job_id)
        return EXIT_USAGE
    _deprioritize()
    layout = jobs.Layout.from_env(args.state_dir)
    return run_job(layout, args.job_id, args.attempt,
                   os.environ.get("SOURCES_URL", ""), os.environ.get("SOURCES_TOKEN", ""))


def cmd_once(args: argparse.Namespace) -> int:
    jobs.setup_logging("once")
    token = os.environ.get("FUENTES_TOKEN") or os.environ.get("SOURCES_TOKEN") or ""
    sources_url = args.sources_url or os.environ.get("SOURCES_URL") or os.environ.get("FUENTES_URL") or ""
    if not token:
        print("error: set FUENTES_TOKEN (e.g. `uv run --env-file .env python -m anon.cli once ...`)", file=sys.stderr)
        return EXIT_USAGE
    if not sources_url:
        print("error: pass --sources-url (or set SOURCES_URL)", file=sys.stderr)
        return EXIT_USAGE
    jobs.register_secret(token)
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    layout = jobs.Layout.from_env(args.state_dir)
    layout.pipeline.mkdir(parents=True, exist_ok=True)

    def progress(event: Any = None, **fields: Any) -> None:
        log.info("progress", extra={"fields": {"progress": _payload(event, fields)}})

    started = time.monotonic()
    try:
        result = jobs.load_pipeline("run_pipeline")(sources_url, token, out, layout.pipeline, progress)
    except Exception as exc:
        jobs.event(log, "once.failed", logging.ERROR, error=jobs.redact(f"{type(exc).__name__}: {exc}"),
                   traceback=jobs.redact(traceback.format_exc()))
        return EXIT_FAILED
    problems = jobs.check_output(out)
    tokens_in, tokens_out = _tokens(result, {})
    summary = {"out": str(out), "records": jobs.count_records(out), "tokens_in": tokens_in,
               "tokens_out": tokens_out, "seconds": round(time.monotonic() - started, 3), "problems": problems}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return EXIT_OK if not problems else EXIT_FAILED


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m anon.cli", description="Anonymization pipeline runner.")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="run one attempt of a job (spawned by the API)")
    run.add_argument("--job-id", required=True)
    run.add_argument("--state-dir", required=True)
    run.add_argument("--attempt", type=int, default=None,
                     help="attempt number assigned by the API (default: take over the current one)")
    once = commands.add_parser("once", help="run the pipeline once into a local folder (token from FUENTES_TOKEN)")
    once.add_argument("--sources-url", default=None, help="sources API root, e.g. https://.../v1")
    once.add_argument("--out", required=True, help="folder for the four output files")
    once.add_argument("--state-dir", default=None,
                      help="pipeline state goes to <state-dir>/pipeline (default: $STATE_DIR or ./state)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    return cmd_once(args)


if __name__ == "__main__":
    exit_code = main()
    if sys.argv[1:2] == ["run"]:
        _hard_exit(exit_code)  # never wait on threads the pipeline may have left running
    sys.exit(exit_code)
