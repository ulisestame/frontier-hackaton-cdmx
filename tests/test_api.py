"""Service-layer tests: HTTP contract, job lifecycle, output promotion, crash recovery.

The real pipeline is swapped for a tiny fake module (written to a temp dir and selected with
ANON_PIPELINE_MODULE), so the runner subprocess path runs for real and the suite stays fast.
The fake's behaviour is driven by FAKE_* environment variables, which the runner inherits.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anon import cli, jobs
from anon.api import create_app

TOKEN = "tok-secret-0123456789"
SOURCES = "http://sources.invalid/v1"
FAKE_MODULE = "fake_pipeline_for_tests"

FAKE_PIPELINE = r'''
import json, os, time
from pathlib import Path


def run_pipeline(sources_url, token, out_dir, state_dir, progress=lambda event: None):
    mode = os.environ.get("FAKE_MODE", "ok")
    tag = os.environ.get("FAKE_TAG", "v1")
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    counter = state_dir / "attempts"
    attempt = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(attempt))
    progress({"stage": "fetch", "attempt": attempt})
    if mode == "crash" or (mode == "crash_once" and attempt == 1):
        os._exit(9)
    if mode == "fail":
        raise RuntimeError("sources API rejected token " + token)
    if mode == "sleep":
        time.sleep(60)
    out = Path(out_dir)
    (out / "chats.jsonl").write_text(json.dumps({"id": "m1", "text": tag}) + "\n", encoding="utf-8")
    gate = os.environ.get("FAKE_GATE")
    if gate:
        deadline = time.time() + 20
        while not Path(gate).exists() and time.time() < deadline:
            time.sleep(0.01)
    if mode == "incomplete":
        return {"records": {"chats": 1, "docs": 0, "tables": 0}}
    (out / "docs.jsonl").write_text(json.dumps({"id": "doc_01", "body": tag}) + "\n", encoding="utf-8")
    rows = "".join(json.dumps({"id": f"clientes:CL-{i}", "tag": tag}) + "\n" for i in range(2))
    (out / "tables.jsonl").write_text(rows, encoding="utf-8")
    (out / "entities.json").write_text(json.dumps({"entities": [{"entity_id": "p_001", "tag": tag}]}), encoding="utf-8")
    progress({"stage": "write", "records": {"chats": 1, "docs": 1, "tables": 2}, "tokens_in": 7})
    return {"records": {"chats": 1, "docs": 1, "tables": 2}, "tokens_in": 10, "tokens_out": 5}


def anonymize_live(source, records, state_dir):
    delay = float(os.environ.get("FAKE_ANON_SLEEP") or 0)
    if delay:
        time.sleep(delay)
    if os.environ.get("FAKE_ANON_FAIL"):
        raise ValueError("boom")
    out = [dict(r, author="Sofia Zambrano") if source == "chats" else r for r in records]
    return {"records": out, "entities": [{"entity_id": "p_001", "type": "person", "originals": [],
                                          "records": [r["id"] for r in records]}]}
'''

CHAT = {"id": "msg-1", "thread_id": "soporte:1.0001", "author": "Manuela", "ts": "1785769807.000100",
        "text": "Hola, me llamo Manuela.", "attachments": [{"filename": "recibo.pdf"}]}
DOC = {"id": "doc_03", "format": "md", "filename": "acta.md", "title": "Acta", "body": "texto",
       "metadata": {"author": "alguien@example.com"}}
ROW = {"id": "clientes:CL-1", "table": "clientes", "columns": {"nombre": "Ana", "edad": 34}}

_ENV_TO_CLEAR = (
    "FAKE_MODE", "FAKE_TAG", "FAKE_GATE", "FAKE_ANON_SLEEP", "FAKE_ANON_FAIL", "TEAM_NAME", "APP_VERSION",
    "LLM_MODELS", "RAILWAY_GIT_COMMIT_SHA", "RUN_TIMEOUT_SECONDS", "MAX_RELAUNCHES", "OUTPUT_KEEP",
    "ANONYMIZE_TIMEOUT_SECONDS", "ANONYMIZE_CONCURRENCY", "FUENTES_TOKEN", "SOURCES_TOKEN", "SOURCES_URL",
)


# --------------------------------------------------------------------------- fixtures and helpers


@pytest.fixture(scope="session")
def fake_dir(tmp_path_factory) -> Path:
    folder = tmp_path_factory.mktemp("fakemods")
    (folder / f"{FAKE_MODULE}.py").write_text(FAKE_PIPELINE, encoding="utf-8")
    return folder


@pytest.fixture
def env(monkeypatch, tmp_path, fake_dir):
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.syspath_prepend(str(fake_dir))
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(fake_dir), os.environ.get("PYTHONPATH")])))
    monkeypatch.setenv("ANON_PIPELINE_MODULE", FAKE_MODULE)
    monkeypatch.setenv("STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("MONITOR_INTERVAL_SECONDS", "0.05")
    return monkeypatch


@pytest.fixture
def layout(env, tmp_path) -> jobs.Layout:
    return jobs.Layout.from_env(tmp_path / "state")


@pytest.fixture
def client(env):
    with TestClient(create_app()) as test_client:
        yield test_client


def wait_for(predicate, timeout: float = 10.0, interval: float = 0.02):
    deadline = time.monotonic() + timeout
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(interval)


def start_run(client: TestClient, **headers: str) -> str:
    response = client.post("/v1/run", json={"sources_url": SOURCES, "token": TOKEN}, headers=headers)
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def wait_final(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    def finished():
        body = client.get(f"/v1/run/{job_id}").json()
        return body if body["status"] in jobs.TERMINAL else None

    return wait_for(finished, timeout)


def write_job(layout: jobs.Layout, job_id: str, status: str, attempt: int, created_at: str | None = None) -> None:
    layout.ensure()
    now = created_at or jobs.utc_now_iso()
    jobs.write_json(layout.status_path(job_id), {
        "job_id": job_id, "status": status, "created_at": now, "started_at": now, "attempt": attempt,
        "records": {"chats": 0, "docs": 0, "tables": 0}, "cost": {"tokens_in": 0, "tokens_out": 0, "seconds": 0},
    })
    jobs.write_json(layout.params_path(job_id), {"sources_url": SOURCES, "token": TOKEN}, mode=0o600)


def cmdline(pid: int) -> str:
    proc = Path(f"/proc/{pid}/cmdline")
    if proc.exists():
        return proc.read_bytes().replace(b"\0", b" ").decode()
    return subprocess.run(["ps", "-ww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                          check=False).stdout


# --------------------------------------------------------------------------- contract basics


def test_health_shape(env):
    env.setenv("LLM_MODELS", "model-a, model-b ,")
    env.setenv("APP_VERSION", "test-1")
    with TestClient(create_app()) as c:
        assert c.get("/v1/health").json() == {"status": "ok", "team": "ulisestame", "version": "test-1",
                                               "models": ["model-a", "model-b"]}
        assert c.head("/v1/health").status_code == 200
    env.setenv("TEAM_NAME", "otro-equipo")
    env.delenv("LLM_MODELS")
    with TestClient(create_app()) as c:
        body = c.get("/v1/health").json()
    assert body["team"] == "otro-equipo" and body["models"] == [] and isinstance(body["version"], str)


def test_root_points_to_health_and_auth_header_is_optional(client):
    for path in ("/", "/v1"):
        response = client.get(path)
        assert response.status_code == 200 and response.json()["health"] == "/v1/health"
    assert client.get("/v1/health", headers={"Authorization": "Bearer whatever"}).status_code == 200
    job_id = start_run(client, Authorization="Bearer whatever")
    assert wait_final(client, job_id)["status"] == "done"


def test_404s_before_any_run(client):
    for name in jobs.OUTPUT_FILES:
        assert client.get(f"/v1/output/{name}").status_code == 404
    assert client.get("/v1/entities").status_code == 404
    assert client.get("/v1/output/secrets.txt").status_code == 404
    assert client.get("/v1/run/unknown-job").status_code == 404
    assert client.get("/v1/run/bad!id").status_code == 404
    assert client.post("/v1/run", json={"sources_url": SOURCES}).status_code == 422
    assert client.post("/v1/run", json={"token": TOKEN}).status_code == 422


def test_run_takes_the_token_from_a_bearer_header_only_when_the_body_has_none(client, env, layout, tmp_path):
    gate = tmp_path / "gate"
    env.setenv("FAKE_GATE", str(gate))  # hold the run so its params file is still there
    response = client.post("/v1/run", json={"sources_url": SOURCES}, headers={"Authorization": "Bearer hdr-tok-987654"})
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    assert json.loads(layout.params_path(job_id).read_text())["token"] == "hdr-tok-987654"
    gate.touch()
    assert wait_final(client, job_id)["status"] == "done"


# --------------------------------------------------------------------------- runs


def test_run_completes_and_serves_output(client, layout):
    job_id = start_run(client)
    body = wait_final(client, job_id)
    assert body["status"] == "done", body
    assert body["records"] == {"chats": 1, "docs": 1, "tables": 2}
    assert body["cost"]["tokens_in"] == 10 and body["cost"]["tokens_out"] == 5
    assert isinstance(body["cost"]["seconds"], float) and body["cost"]["seconds"] >= 0
    assert "error" not in body and body["relaunches"] == 0
    assert jobs.parse_iso(body["started_at"]) <= jobs.parse_iso(body["finished_at"])

    chats = client.get("/v1/output/chats.jsonl")
    assert chats.status_code == 200 and chats.headers["content-type"].startswith("application/x-ndjson")
    assert json.loads(chats.text.splitlines()[0])["text"] == "v1"
    entities = client.get("/v1/output/entities.json")
    assert entities.headers["content-type"].startswith("application/json")
    assert entities.json()["entities"][0]["tag"] == "v1"
    assert client.get("/v1/entities").json() == entities.json()
    assert client.head("/v1/output/tables.jsonl").status_code == 200

    assert jobs.current_job_id(layout) == job_id
    assert not list(layout.output.glob("*.tmp"))
    assert not layout.params_path(job_id).exists()
    assert TOKEN not in layout.status_path(job_id).read_text()


def test_run_is_idempotent_while_active(client, env, tmp_path):
    gate = tmp_path / "gate"
    env.setenv("FAKE_GATE", str(gate))
    first = start_run(client)
    assert start_run(client) == first
    running = client.get(f"/v1/run/{first}").json()
    assert running["status"] in ("queued", "running")
    assert "finished_at" not in running and "error" not in running  # omitted, never null
    gate.touch()
    assert wait_final(client, first)["status"] == "done"
    second = start_run(client)
    assert second != first
    assert wait_final(client, second)["status"] == "done"


def test_current_switches_only_after_the_output_is_complete(client, env, layout, tmp_path):
    first = start_run(client)
    assert wait_final(client, first)["status"] == "done"

    gate = tmp_path / "gate"
    env.setenv("FAKE_GATE", str(gate))
    env.setenv("FAKE_TAG", "v2")
    second = start_run(client)
    wait_for(lambda: (layout.tmp_output(second, 1) / "chats.jsonl").exists())  # partial output on disk
    assert client.get(f"/v1/run/{second}").json()["status"] == "running"
    assert jobs.current_job_id(layout) == first
    assert json.loads(client.get("/v1/output/chats.jsonl").text)["text"] == "v1"
    assert client.get("/v1/entities").json()["entities"][0]["tag"] == "v1"

    gate.touch()
    assert wait_final(client, second)["status"] == "done"
    assert jobs.current_job_id(layout) == second
    assert json.loads(client.get("/v1/output/chats.jsonl").text)["text"] == "v2"
    assert sorted(p.name for p in layout.output.iterdir() if p.is_dir()) == sorted([first, second])


def test_failed_run_keeps_previous_output_and_masks_the_token(client, env, layout):
    first = start_run(client)
    assert wait_final(client, first)["status"] == "done"
    env.setenv("FAKE_MODE", "fail")
    second = start_run(client)
    body = wait_final(client, second)
    assert body["status"] == "failed" and "finished_at" in body
    assert body["error"].startswith("RuntimeError") and "***" in body["error"] and TOKEN not in body["error"]
    assert jobs.current_job_id(layout) == first
    assert client.get("/v1/output/chats.jsonl").status_code == 200
    assert TOKEN not in layout.status_path(second).read_text()
    assert not layout.params_path(second).exists()
    assert not list(layout.output.glob("*.tmp"))


def test_incomplete_output_fails_the_run(client, env, layout):
    env.setenv("FAKE_MODE", "incomplete")
    body = wait_final(client, start_run(client))
    assert body["status"] == "failed" and "missing docs.jsonl" in body["error"]
    assert jobs.current_job_id(layout) is None
    assert client.get("/v1/output/chats.jsonl").status_code == 404


def test_token_travels_by_environment_and_params_file_is_private(client, env, layout, tmp_path):
    gate = tmp_path / "gate"
    env.setenv("FAKE_GATE", str(gate))
    job_id = start_run(client)
    pid = wait_for(lambda: jobs.runner_pids(job_id))[0]
    command = cmdline(pid)
    assert job_id in command and TOKEN not in command
    assert stat.S_IMODE(layout.params_path(job_id).stat().st_mode) == 0o600
    assert json.loads(layout.params_path(job_id).read_text())["token"] == TOKEN
    gate.touch()
    assert wait_final(client, job_id)["status"] == "done"
    assert not layout.params_path(job_id).exists()


# --------------------------------------------------------------------------- watchdog and relaunches


def test_watchdog_kills_a_run_over_the_time_limit(env):
    env.setenv("RUN_TIMEOUT_SECONDS", "0.6")
    env.setenv("FAKE_MODE", "sleep")
    with TestClient(create_app()) as c:
        job_id = start_run(c)
        wait_for(lambda: jobs.runner_pids(job_id))
        body = wait_final(c, job_id)
        assert body["status"] == "failed" and body["error"] == "timeout"
        wait_for(lambda: not jobs.runner_pids(job_id), timeout=5)


def test_a_crashed_runner_is_relaunched(client, env, layout):
    env.setenv("FAKE_MODE", "crash_once")
    job_id = start_run(client)
    body = wait_final(client, job_id)
    assert body["status"] == "done" and body["relaunches"] == 1
    assert jobs.current_job_id(layout) == job_id


def test_relaunches_stop_at_the_limit(client, env, layout):
    env.setenv("FAKE_MODE", "crash")
    job_id = start_run(client)
    body = wait_final(client, job_id)
    assert body["status"] == "failed" and "relaunch limit" in body["error"] and "signal 9" not in body["error"]
    assert body["relaunches"] == 2
    assert (layout.pipeline / "attempts").read_text() == "3"
    assert not layout.params_path(job_id).exists()


def test_startup_relaunches_a_job_whose_runner_is_gone(env, layout):
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    job_id = "20260101-000000-abcdef"
    write_job(layout, job_id, "running", attempt=1)
    jobs.update_status(layout, job_id, lambda status: status.update(pid=dead.pid))
    with TestClient(create_app()) as c:
        assert c.post("/v1/run", json={"sources_url": SOURCES, "token": TOKEN}).json()["job_id"] == job_id
        body = wait_final(c, job_id)
    assert body["status"] == "done" and body["relaunches"] == 1
    assert jobs.current_job_id(layout) == job_id


def test_startup_gives_up_after_the_limit_and_abandons_older_jobs(env, layout):
    older, newest = "20260101-000000-000001", "20260101-000001-000002"
    write_job(layout, older, "queued", attempt=1, created_at="2026-01-01T00:00:00.000Z")
    write_job(layout, newest, "running", attempt=3)
    with TestClient(create_app()) as c:
        body = c.get(f"/v1/run/{newest}").json()
        assert body["status"] == "failed" and "relaunch limit" in body["error"]
        assert "abandoned" in c.get(f"/v1/run/{older}").json()["error"]
        assert start_run(c) not in (older, newest)  # nothing active any more
    assert not layout.params_path(newest).exists() and not layout.params_path(older).exists()


def test_startup_adopts_a_runner_that_is_still_alive(env, layout, tmp_path):
    gate = tmp_path / "gate"
    env.setenv("FAKE_GATE", str(gate))
    job_id = "20260101-000000-a1b2c3"
    write_job(layout, job_id, "queued", attempt=1)
    handle = jobs.SubprocessLauncher().launch(layout, job_id, 1, {"sources_url": SOURCES, "token": TOKEN})
    try:
        wait_for(lambda: (jobs.read_status(layout, job_id) or {}).get("status") == "running")
        with TestClient(create_app()) as c:
            gate.touch()
            body = wait_final(c, job_id)
        assert body["status"] == "done" and body["relaunches"] == 0
    finally:
        handle.kill()


# --------------------------------------------------------------------------- /anonymize


def test_anonymize_validates_the_schema(client):
    def post(source, records):
        return client.post("/v1/anonymize", json={"source": source, "records": records})

    assert post("emails", [CHAT]).status_code == 422
    assert post("chats", [CHAT] * 51).status_code == 422
    missing = post("chats", [{"id": "msg-1", "text": "hola"}])
    assert missing.status_code == 422
    assert ["body", "records", 0, "thread_id"] in [err["loc"] for err in missing.json()["detail"]]
    assert post("docs", [dict(DOC, format="docx")]).status_code == 422
    assert post("tables", [dict(ROW, columns={"nombre": {"nested": "x"}})]).status_code == 422
    assert post("chats", [ROW]).status_code == 422  # a table row is not a chat record
    assert client.post("/v1/anonymize", json={"records": [CHAT]}).status_code == 422

    assert post("chats", []).json() == {"records": [], "entities": []}
    ok = post("chats", [dict(CHAT, extra_field="kept")] * 50)
    assert ok.status_code == 200
    body = ok.json()
    assert len(body["records"]) == 50 and body["records"][0]["id"] == "msg-1"
    assert body["records"][0]["author"] == "Sofia Zambrano" and body["records"][0]["extra_field"] == "kept"
    assert body["entities"][0]["entity_id"] == "p_001"
    row = post("tables", [ROW]).json()["records"][0]
    assert row["columns"] == {"nombre": "Ana", "edad": "34"}  # numbers arrive as text
    assert post("docs", [DOC]).status_code == 200


def test_anonymize_calls_the_pipeline_with_the_shared_state_dir(client, layout, monkeypatch):
    import fake_pipeline_for_tests as fake

    calls = []

    def spy(source, records, state_dir):
        calls.append((source, [r["id"] for r in records], Path(state_dir)))
        return {"records": records}  # no "entities" key: the API fills in []

    monkeypatch.setattr(fake, "anonymize_live", spy)
    body = client.post("/v1/anonymize", json={"source": "chats", "records": [CHAT]},
                       headers={"Authorization": "Bearer x"}).json()
    assert body == {"records": [CHAT], "entities": []}
    assert calls == [("chats", ["msg-1"], layout.pipeline)]


def test_anonymize_timeout_and_errors(env):
    env.setenv("ANONYMIZE_TIMEOUT_SECONDS", "0.2")
    env.setenv("FAKE_ANON_SLEEP", "1")
    with TestClient(create_app()) as c:
        started = time.monotonic()
        response = c.post("/v1/anonymize", json={"source": "chats", "records": [CHAT]})
        assert response.status_code == 504 and time.monotonic() - started < 0.9
        assert c.get("/v1/health").status_code == 200
        env.delenv("FAKE_ANON_SLEEP")
        env.setenv("FAKE_ANON_FAIL", "1")
        failed = c.post("/v1/anonymize", json={"source": "chats", "records": [CHAT]})
        assert failed.status_code == 500 and "ValueError" in failed.json()["detail"]


# --------------------------------------------------------------------------- units


def test_run_job_in_process_with_a_monkeypatched_pipeline(env, layout):
    seen = {}

    def fake_pipeline(sources_url, token, out_dir, state_dir, progress):
        seen.update(sources_url=sources_url, token=token, out_dir=Path(out_dir), state_dir=Path(state_dir))
        progress({"stage": "tables", "records": {"tables": 2}})
        for name in ("chats.jsonl", "docs.jsonl", "tables.jsonl"):
            (Path(out_dir) / name).write_text('{"id": "a"}\n{"id": "b"}\n', encoding="utf-8")
        (Path(out_dir) / "entities.json").write_text('{"entities": []}', encoding="utf-8")
        return {"records": {"chats": 2, "docs": 2, "tables": 2}, "tokens_in": 3, "tokens_out": 4}

    job_id = "20260101-000000-feed00"
    write_job(layout, job_id, "queued", attempt=1)
    assert cli.run_job(layout, job_id, 1, SOURCES, TOKEN, pipeline_fn=fake_pipeline) == cli.EXIT_OK
    assert seen == {"sources_url": SOURCES, "token": TOKEN, "out_dir": layout.tmp_output(job_id, 1),
                    "state_dir": layout.pipeline}
    status = jobs.read_status(layout, job_id)
    assert status["status"] == "done" and status["records"] == {"chats": 2, "docs": 2, "tables": 2}
    assert status["cost"]["tokens_in"] == 3 and status["progress"]["stage"] == "tables"
    assert jobs.current_job_id(layout) == job_id and not layout.params_path(job_id).exists()
    # a stale attempt can never take over a job
    assert cli.run_job(layout, job_id, 1, SOURCES, TOKEN, pipeline_fn=fake_pipeline) == cli.EXIT_NOT_MINE


def test_prune_keeps_the_newest_outputs_and_current(tmp_path):
    layout = jobs.Layout.from_env(tmp_path / "state")
    layout.ensure()
    names = [f"2026010{i}-000000-aaaaaa" for i in range(1, 6)]
    for offset, name in enumerate(names):
        folder = layout.final_output(name)
        folder.mkdir()
        os.utime(folder, (1_000 + offset, 1_000 + offset))
    (layout.output / f"{names[0]}.2.tmp").mkdir()
    jobs.atomic_write_bytes(layout.current_file, f"{names[0]}\n".encode())  # CURRENT on the oldest
    assert sorted(jobs.prune_outputs(layout, keep=3)) == [names[1]]
    remaining = sorted(p.name for p in layout.output.iterdir() if p.is_dir())
    assert remaining == sorted([names[0], names[2], names[3], names[4], f"{names[0]}.2.tmp"])


def test_cli_once_writes_a_local_output(env, tmp_path, capsys):
    out = tmp_path / "out"
    assert cli.main(["once", "--sources-url", SOURCES, "--out", str(out)]) == cli.EXIT_USAGE  # no token
    env.setenv("FUENTES_TOKEN", TOKEN)
    assert cli.main(["once", "--sources-url", SOURCES, "--out", str(out), "--state-dir", str(tmp_path / "st")]) == 0
    assert all((out / name).is_file() for name in jobs.OUTPUT_FILES)
    summary = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert summary["records"] == {"chats": 1, "docs": 1, "tables": 2} and summary["problems"] == []
