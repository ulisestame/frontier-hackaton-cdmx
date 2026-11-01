# Anonymization service image (Railway or any Docker host).
#   docker build -t anon .
#   docker run -p 9000:9000 -v anon-data:/data anon
# State (job files, outputs, the pseudonym map) lives in STATE_DIR=/data/state: mount a volume at /data.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.11 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so this layer stays cached while only src/ changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ ./src/
COPY run.sh ./run.sh
RUN uv sync --frozen --no-dev && chmod +x run.sh

# run.sh uses ANON_PYTHON directly, so uv never re-syncs (or touches the network) at startup.
ENV PATH="/app/.venv/bin:$PATH" \
    ANON_PYTHON=/app/.venv/bin/python \
    STATE_DIR=/data/state \
    PORT=9000

EXPOSE 9000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/v1/health' % os.environ.get('PORT', '9000'), timeout=4)"]

# bash is PID 1: run.sh forwards SIGTERM to uvicorn and restarts it if it dies.
CMD ["./run.sh"]
