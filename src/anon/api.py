"""HTTP API under /v1 (contract: material-reto/api/participante.openapi.yaml).

No authentication: an Authorization header is accepted and ignored. Long work never runs on
the request path. POST /run hands the pipeline to a supervised child process (jobs.py), and
POST /anonymize runs in a small pool of daemon threads behind a hard timeout, so /health and
the status endpoints keep answering while a run is in progress.

The pipeline module is imported lazily (and warmed up in the background at startup), so an
import error in it surfaces as a failed run or a 500 from /anonymize, never as a dead service.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from anon import jobs

log = logging.getLogger("anon.api")

PREFIX = "/v1"
MAX_BATCH = 50
DEFAULT_TEAM = "ulisestame"
FALLBACK_VERSION = "0.1.0"
MEDIA_TYPES = {".jsonl": "application/x-ndjson", ".json": "application/json"}


# --------------------------------------------------------------------------- /health


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=2, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else None


def health_payload() -> dict[str, Any]:
    version = (
        os.environ.get("APP_VERSION", "").strip()
        or os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip()[:7]
        or _git_sha()
        or FALLBACK_VERSION
    )
    models = [name.strip() for name in os.environ.get("LLM_MODELS", "").split(",") if name.strip()]
    team = os.environ.get("TEAM_NAME", "").strip() or DEFAULT_TEAM
    return {"status": "ok", "team": team, "version": version, "models": models}


# --------------------------------------------------------------------------- request bodies


class RunRequest(BaseModel):
    sources_url: str = Field(min_length=1)
    token: str | None = None  # required by the contract; a Bearer header is used only when it is absent


class _Record(BaseModel):
    # Unknown keys are kept and passed through; numbers sent where the schema says text become text.
    model_config = ConfigDict(extra="allow", coerce_numbers_to_str=True)


class Attachment(_Record):
    filename: str


class ChatRecord(_Record):
    id: str
    thread_id: str
    author: str
    ts: str
    text: str
    attachments: list[Attachment]


class DocRecord(_Record):
    id: str
    format: Literal["pdf", "html", "md"]
    filename: str
    title: str
    body: str
    metadata: dict[str, str]


class TableRecord(_Record):
    id: str
    table: Literal["clientes", "transacciones", "pqrs", "empleados"]
    columns: dict[str, str]


RECORD_ADAPTERS: dict[str, TypeAdapter] = {
    "chats": TypeAdapter(list[ChatRecord]),
    "docs": TypeAdapter(list[DocRecord]),
    "tables": TypeAdapter(list[TableRecord]),
}


class AnonymizeRequest(BaseModel):
    source: Literal["chats", "docs", "tables"]
    records: list[dict[str, Any]] = Field(max_length=MAX_BATCH)


def _record_errors(exc: ValidationError) -> list[dict[str, Any]]:
    # Same shape as FastAPI's own 422 details, without echoing the records back.
    return [
        {"type": err["type"], "loc": ["body", "records", *err["loc"]], "msg": err["msg"]}
        for err in exc.errors(include_url=False)
    ]


# --------------------------------------------------------------------------- plumbing


class DaemonPool:
    """Fixed-size pool of daemon threads, so an anonymize call that never returns cannot block shutdown."""

    def __init__(self, size: int, name: str) -> None:
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._size = max(1, size)
        for index in range(self._size):
            threading.Thread(target=self._work, name=f"{name}-{index}", daemon=True).start()

    def submit(self, fn: Callable[..., Any], *args: Any) -> concurrent.futures.Future:
        future: concurrent.futures.Future = concurrent.futures.Future()
        self._queue.put((future, fn, args))
        return future

    def close(self) -> None:
        for _ in range(self._size):
            self._queue.put(None)

    def _work(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn, args = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args))
            except BaseException as exc:  # noqa: BLE001 - handed to the awaiting request
                future.set_exception(exc)


class AccessLogMiddleware:
    """One structured line per request (method, path, status, ms). Never logs bodies or query strings."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = {"code": 500}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            jobs.event(log, "http", method=scope.get("method"), path=scope.get("path"), status=status["code"],
                       ms=round((time.perf_counter() - started) * 1000, 1))


def _anonymize_sync(source: str, records: list[dict], state_dir: Path) -> Any:
    return jobs.load_pipeline("anonymize_live")(source, records, state_dir)


def _warm_pipeline() -> None:
    started = time.monotonic()
    try:
        jobs.load_pipeline("anonymize_live")
    except Exception:
        jobs.event(log, "pipeline.import_failed", logging.ERROR, exc_info=True, module=jobs.pipeline_module_name())
    else:
        jobs.event(log, "pipeline.imported", module=jobs.pipeline_module_name(),
                   ms=round((time.monotonic() - started) * 1000, 1))


def _check_volume(layout: jobs.Layout) -> None:
    """On Railway, warn loudly when STATE_DIR is not on a mounted volume (state would die with each deploy)."""
    if not any(key.startswith("RAILWAY_") for key in os.environ):
        return
    mount = layout.root
    while not os.path.ismount(mount):
        mount = mount.parent
    if str(mount) == "/":
        jobs.event(log, "state.not_on_volume", logging.WARNING, state_dir=str(layout.root),
                   detail="STATE_DIR is not on a mounted volume: pseudonym state and outputs are lost on redeploy")


def _not_found(detail: str) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": detail})


# --------------------------------------------------------------------------- the app


def create_app(
    state_dir: str | os.PathLike[str] | None = None,
    *,
    launcher: Any = None,
    settings: jobs.Settings | None = None,
) -> FastAPI:
    """Build the app. Configuration is read from the environment at startup, not at import."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        jobs.setup_logging("api")
        layout = jobs.Layout.from_env(state_dir)
        manager = jobs.JobManager(layout, settings=settings, launcher=launcher)
        concurrency = max(1, jobs.env_int("ANONYMIZE_CONCURRENCY", 4))
        app.state.layout = layout
        app.state.jobs = manager
        app.state.health = health_payload()
        app.state.anonymize_timeout = jobs.env_float("ANONYMIZE_TIMEOUT_SECONDS", 55.0)
        app.state.anonymize_pool = DaemonPool(concurrency, "anonymize")
        try:
            manager.startup()
        except Exception:
            jobs.event(log, "api.startup_failed", logging.ERROR, exc_info=True, state_dir=str(layout.root))
        _check_volume(layout)
        threading.Thread(target=_warm_pipeline, name="pipeline-warmup", daemon=True).start()
        jobs.event(
            log, "api.started", state_dir=str(layout.root), version=app.state.health["version"],
            pipeline=jobs.pipeline_module_name(), run_timeout_s=manager.settings.run_timeout,
            max_relaunches=manager.settings.max_relaunches, keep_outputs=manager.settings.keep_outputs,
            anonymize_timeout_s=app.state.anonymize_timeout, anonymize_concurrency=concurrency,
            active_job=manager.active_job_id(),
        )
        try:
            yield
        finally:
            manager.shutdown()
            app.state.anonymize_pool.close()
            jobs.event(log, "api.stopped")

    app = FastAPI(title="Reto PII - anon", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "HEAD", "POST", "OPTIONS"],
                       allow_headers=["*"])
    app.add_middleware(AccessLogMiddleware)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        jobs.event(log, "http.unhandled", logging.ERROR, exc_info=exc, path=request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    @app.get("/", include_in_schema=False)
    @app.head("/", include_in_schema=False)
    @app.get(PREFIX, include_in_schema=False)
    @app.head(PREFIX, include_in_schema=False)
    async def root() -> dict[str, str]:
        return {"service": "anon", "health": f"{PREFIX}/health", "docs": "/docs"}

    @app.get(f"{PREFIX}/health")
    @app.head(f"{PREFIX}/health", include_in_schema=False)
    async def health(request: Request) -> dict[str, Any]:
        return getattr(request.app.state, "health", None) or health_payload()

    @app.post(f"{PREFIX}/run", status_code=202)
    def start_run(body: RunRequest, request: Request) -> JSONResponse:
        # Sync on purpose: it takes locks and spawns a process, so it runs in the threadpool.
        token = body.token
        if token is None:
            scheme, _, value = request.headers.get("authorization", "").partition(" ")
            token = value.strip() if scheme.lower() == "bearer" and value.strip() else None
        if token is None:
            return JSONResponse(status_code=422, content={"detail": [
                {"type": "missing", "loc": ["body", "token"], "msg": "Field required"}]})
        manager: jobs.JobManager = request.app.state.jobs
        job_id, created = manager.submit(body.sources_url, token)
        status = manager.get(job_id) or {}
        jobs.event(log, "run.requested", job_id=job_id, created=created, status=status.get("status"))
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": status.get("status", "queued")})

    @app.get(f"{PREFIX}/run/{{job_id}}")
    async def run_status(job_id: str, request: Request) -> Any:
        status = request.app.state.jobs.get(job_id)
        if status is None:
            return _not_found("unknown job_id")
        return jobs.public_status(status)

    @app.get(f"{PREFIX}/output/{{archivo}}")
    @app.head(f"{PREFIX}/output/{{archivo}}", include_in_schema=False)
    async def output(archivo: str, request: Request) -> Any:
        if archivo not in jobs.OUTPUT_FILES:
            return _not_found("unknown file; expected one of " + ", ".join(jobs.OUTPUT_FILES))
        path = jobs.output_file(request.app.state.layout, archivo)
        if path is None:
            return _not_found("no finished run yet")
        return FileResponse(path, media_type=MEDIA_TYPES[path.suffix])

    @app.get(f"{PREFIX}/entities")
    async def entities(request: Request) -> Any:
        path = jobs.output_file(request.app.state.layout, "entities.json")
        if path is None:
            return _not_found("no finished run yet")
        return FileResponse(path, media_type="application/json")

    @app.post(f"{PREFIX}/anonymize")
    async def anonymize(body: AnonymizeRequest, request: Request) -> Any:
        try:
            parsed = RECORD_ADAPTERS[body.source].validate_python(body.records)
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"detail": _record_errors(exc)})
        records = [record.model_dump() for record in parsed]
        if not records:
            return {"records": [], "entities": []}
        state = request.app.state
        timeout = state.anonymize_timeout
        started = time.monotonic()
        future = asyncio.wrap_future(state.anonymize_pool.submit(_anonymize_sync, body.source, records,
                                                                 state.layout.pipeline))
        done, _ = await asyncio.wait({future}, timeout=timeout)
        if not done:
            future.cancel()  # drops the call if it never started; a running thread is left to finish
            jobs.event(log, "anonymize.timeout", logging.ERROR, source=body.source, records=len(records),
                       timeout_s=timeout)
            return JSONResponse(status_code=504, content={"detail": f"anonymize timed out after {timeout:g}s"})
        try:
            result = future.result()
        except Exception as exc:
            jobs.event(log, "anonymize.failed", logging.ERROR, exc_info=exc, source=body.source, records=len(records))
            return JSONResponse(status_code=500, content={"detail": f"anonymize failed: {type(exc).__name__}: {exc}"})
        if not isinstance(result, dict) or not isinstance(result.get("records"), list):
            jobs.event(log, "anonymize.bad_result", logging.ERROR, source=body.source, got=type(result).__name__)
            return JSONResponse(status_code=500, content={"detail": "anonymize_live returned an invalid result"})
        found = result.get("entities")
        payload = jsonable_encoder({"records": result["records"], "entities": found if isinstance(found, list) else []})
        jobs.event(log, "anonymize.ok", source=body.source, records=len(records), entities=len(payload["entities"]),
                   ms=round((time.monotonic() - started) * 1000, 1))
        return JSONResponse(content=payload)

    return app


app = create_app()
