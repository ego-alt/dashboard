ARG PYTHON_VERSION=3.11

# ---- builder: resolve deps into a venv with uv ----
FROM python:${PYTHON_VERSION}-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY homehub_mcp ./homehub_mcp
RUN uv sync --frozen --no-dev

# ---- runtime ----
FROM python:${PYTHON_VERSION}-slim AS runtime

RUN useradd --create-home --shell /bin/bash --uid 10001 app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MCP_DB=/data/mcp.db

USER app
EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/healthz')"

CMD ["homehub-mcp", "--http"]
