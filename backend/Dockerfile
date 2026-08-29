FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --all-groups --no-install-project

COPY alembic ./alembic
COPY src ./src
COPY tests ./tests
COPY tools ./tools
COPY alembic.ini ./
RUN uv sync --frozen --all-groups

RUN useradd --create-home --uid 10001 workshop \
    && mkdir -p /data/objects \
    && chown -R workshop:workshop /app /data

USER workshop

EXPOSE 8000

CMD ["uvicorn", "ai_workshop.main:app", "--host", "0.0.0.0", "--port", "8000"]
