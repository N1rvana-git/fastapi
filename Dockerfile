# Multi-stage image for the API (and, with a different command, the worker).
#
# Design notes:
# * `uv` resolves/installs an order of magnitude faster than pip and respects
#   the same requirements file.
# * heavy AI extras are opt-in via `--build-arg INSTALL_AI=1`.
# * NO database migration in CMD. `alembic upgrade head` belongs to the deploy
#   pipeline (docker compose `migrate` service / K8s Job); N replicas racing the
#   same migration corrupts the schema.
# * runs as an unprivileged user and ships a liveness healthcheck.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /bin/uv

WORKDIR /app
COPY requirements.txt requirements-ai.txt ./

ARG INSTALL_AI=0
RUN uv pip install --system -r requirements.txt \
    && if [ "$INSTALL_AI" = "1" ]; then uv pip install --system -r requirements-ai.txt; fi

COPY . .
RUN python -m compileall -q src

FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONFAULTHANDLER=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 appuser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app /app

WORKDIR /app
RUN mkdir -p /app/uploads /app/static && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health/live || exit 1

# One process per container: scale with replicas, not workers, so that
# graceful shutdown, memory limits and probes stay predictable.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--proxy-headers", "--forwarded-allow-ips=*"]

# Worker command (override CMD):
#   docker run --rm <image> python -m src.worker
