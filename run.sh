#!/usr/bin/env bash
# Start the anonymization API: uvicorn with a single worker on ${HOST:-0.0.0.0}:${PORT:-9000}.
#
# Job state lives on disk under $STATE_DIR (default ./state), so one worker process keeps the
# bookkeeping simple. This script also supervises uvicorn: if the server dies unexpectedly it is
# started again a second later, while a pipeline run keeps going in its own process and is picked
# up by the new server. SIGTERM / SIGINT stop everything cleanly. Five quick failures in a row
# (server up for less than 10 s each) end the script with status 1, so the platform sees a crash.
#
# Interpreter: $ANON_PYTHON when set (the Docker image points it at /app/.venv/bin/python),
# else `uv run` when uv is installed, else python3 from PATH.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 1

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-9000}"
export STATE_DIR="${STATE_DIR:-$ROOT/state}"
export PYTHONUNBUFFERED=1

if [ -n "${ANON_PYTHON:-}" ]; then
  PY=("$ANON_PYTHON")
elif command -v uv >/dev/null 2>&1; then
  PY=(uv run --frozen python)
else
  PY=(python3)
fi

# --timeout-keep-alive above the usual 60 s proxy idle timeout avoids sporadic 502s behind Railway's edge.
SERVER=("${PY[@]}" -m uvicorn anon.api:app
  --app-dir "$ROOT/src"
  --host "$HOST" --port "$PORT" --workers 1
  --no-access-log --proxy-headers --forwarded-allow-ips '*'
  --timeout-keep-alive 75 --timeout-graceful-shutdown 10)

log() {  # log LEVEL EVENT DETAIL [EXTRA_JSON_FIELDS]; Railway shows "message"
  printf '{"message":"%s %s","event":"%s","level":"%s","ts":"%s","proc":"run.sh"%s}\n' \
    "$2" "$3" "$2" "$1" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${4:-}"
}

child=0
stopping=0
on_signal() {
  stopping=1
  if [ "$child" -ne 0 ]; then
    kill -TERM "$child" 2>/dev/null || true
  fi
}
trap on_signal TERM INT HUP

fast_failures=0
log info server.start "host=$HOST port=$PORT state_dir=$STATE_DIR" \
  ",\"host\":\"$HOST\",\"port\":$PORT,\"state_dir\":\"$STATE_DIR\""
while :; do
  started=$(date +%s)
  "${SERVER[@]}" &
  child=$!
  rc=0
  # `wait` returns early when a trapped signal arrives; keep waiting until the server is gone.
  while kill -0 "$child" 2>/dev/null; do
    wait "$child"
    rc=$?
  done
  child=0
  if [ "$stopping" -eq 1 ]; then
    log info server.stopped "rc=$rc" ",\"rc\":$rc"
    exit 0
  fi
  uptime=$(( $(date +%s) - started ))
  if [ "$uptime" -lt 10 ]; then fast_failures=$((fast_failures + 1)); else fast_failures=0; fi
  if [ "$fast_failures" -ge 5 ]; then
    log error server.giving_up "rc=$rc: server exited 5 times in a row within 10 s of starting" ",\"rc\":$rc"
    exit 1
  fi
  log error server.exited "rc=$rc uptime_s=$uptime, restarting in 1 s" ",\"rc\":$rc,\"uptime_s\":$uptime"
  sleep 1
  if [ "$stopping" -eq 1 ]; then
    exit 0
  fi
done
