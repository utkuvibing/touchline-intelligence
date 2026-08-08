# Backend image for Railway.
#
# Multi-stage: dependencies are resolved once in a builder and the resulting virtualenv is copied
# into a slim runtime. The runtime carries no build toolchain and no uv, which keeps the deployed
# surface to the interpreter and the locked dependencies.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies before source: this layer is rebuilt only when the lockfile changes, so ordinary
# code changes redeploy without re-resolving anything.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project --no-default-groups

COPY backend ./backend
COPY README.md ./
RUN uv sync --locked --no-default-groups


FROM python:3.12-slim-bookworm AS runtime

# Never runs as root. Railway does not require it; it is simply the correct default and costs
# nothing to set here rather than after an incident.
RUN useradd --create-home --uid 10001 touchline

WORKDIR /app

COPY --from=builder --chown=touchline:touchline /app/.venv /app/.venv
COPY --from=builder --chown=touchline:touchline /app/backend /app/backend

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER touchline

# Railway injects PORT. The default keeps `docker run -p 8000:8000 <image>` working locally without
# having to remember to pass it.
ENV PORT=8000
EXPOSE 8000

# `sh -c` so ${PORT} is expanded at runtime rather than baked in at build time, and `exec` so
# uvicorn replaces the shell as PID 1. Without the exec, SIGTERM would go to sh and uvicorn would
# be killed rather than shut down, which is how a platform redeploy turns into dropped requests.
CMD ["sh", "-c", "exec uvicorn touchline.main:app --host 0.0.0.0 --port ${PORT} --app-dir backend/src"]
