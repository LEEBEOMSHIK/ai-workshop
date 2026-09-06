FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS application-base

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY alembic ./alembic
COPY src ./src
COPY tools ./tools
COPY alembic.ini ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN useradd --no-log-init --create-home --uid 10001 workshop \
    && mkdir -p /data/objects \
    && chown -R workshop:workshop /data

FROM application-base AS embedding-base

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra embedding-cpu

FROM embedding-base AS runtime-embedding-cpu

USER workshop

EXPOSE 8000

CMD ["uvicorn", "ai_workshop.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM embedding-base AS ocr-base

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra embedding-cpu --extra ocr-cpu

FROM ocr-base AS runtime-ocr-cpu

USER workshop

EXPOSE 8000

CMD ["uvicorn", "ai_workshop.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM embedding-base AS runtime-test

COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-groups --extra embedding-cpu

USER workshop

FROM ocr-base AS runtime-ocr-test

COPY tests ./tests
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-groups --extra embedding-cpu --extra ocr-cpu

USER workshop

FROM application-base AS runtime-core

USER workshop

EXPOSE 8000

CMD ["uvicorn", "ai_workshop.main:app", "--host", "0.0.0.0", "--port", "8000"]
