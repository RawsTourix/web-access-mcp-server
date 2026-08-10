# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:0.11.32 AS uv

FROM python:3.11.9-slim-bookworm AS builder
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.11.9-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --gid 10001 webaccess \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin webaccess \
    && mkdir -p /var/lib/web-access/content \
    && chown -R 10001:10001 /var/lib/web-access /app
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 alembic.ini ./alembic.ini
COPY --chown=10001:10001 alembic ./alembic
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "--factory", "web_access.entrypoints.api:create_app", "--host", "0.0.0.0", "--port", "8000"]

