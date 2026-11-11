# Hauntlet range for a single hosted instance (Render free web service, render.yaml).
#
# Dependencies come from uv.lock exactly (--frozen); the app runs as a non-root
# user. All range state (event store, scratch workspaces, Exorcist bundles,
# fact-log copies) lives under /tmp/hauntlet and is lost on restart, which is
# fine: hosted bundles are kept for one hour anyway.

# uv 0.11.14
FROM ghcr.io/astral-sh/uv@sha256:1025398289b62de8269e70c45b91ffa37c373f38118d7da036fb8bb8efc85d97 AS uv

# python:3.12-slim
FROM python@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, so source edits do not reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev && rm /usr/local/bin/uv

RUN useradd --system --uid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin hauntlet \
    && mkdir -p /tmp/hauntlet/reports && chown -R hauntlet /tmp/hauntlet

ENV PATH=/app/.venv/bin:$PATH \
    HAUNTLET_DB=/tmp/hauntlet/range.db \
    HAUNTLET_REPORTS_DIR=/tmp/hauntlet/reports \
    HAUNTLET_EXORCIST_DEMO_ROOMS=cursed-repo,poltergeist \
    FORWARDED_ALLOW_IPS=* \
    PORT=8666

USER hauntlet
EXPOSE 8666

# sh expands $PORT (set by Render); exec makes uvicorn PID 1, so it gets SIGTERM.
CMD ["sh", "-c", "exec hauntlet serve --host 0.0.0.0 --port \"$PORT\""]
