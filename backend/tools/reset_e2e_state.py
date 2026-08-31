from asyncio import run, sleep
from collections.abc import Awaitable, Callable, Mapping
from os import environ

from redis.asyncio import Redis
from sqlalchemy import text

from ai_workshop.config import Settings
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.shared.db import create_engine
from tools.e2e_runtime import E2ERuntimeContractError, build_reset_scope

DatabaseReset = Callable[[Settings, tuple[str, ...]], Awaitable[None]]
RedisReset = Callable[[Settings, int], Awaitable[None]]
ElasticsearchReset = Callable[[Settings, str], Awaitable[None]]
ReadinessCheck = Callable[[Settings], Awaitable[None]]


async def reset_e2e_state(
    settings: Settings,
    environment: Mapping[str, str],
    *,
    readiness_check: ReadinessCheck | None = None,
    database_reset: DatabaseReset | None = None,
    redis_reset: RedisReset | None = None,
    elasticsearch_reset: ElasticsearchReset | None = None,
) -> None:
    scope = build_reset_scope(settings, environment)
    await (readiness_check or _wait_for_reset_targets)(settings)
    await (database_reset or _reset_database)(settings, scope.database_tables)
    await (redis_reset or _reset_redis)(settings, scope.redis_database)
    await (elasticsearch_reset or _reset_elasticsearch)(
        settings, scope.elasticsearch_index_pattern
    )


async def _wait_for_reset_targets(settings: Settings) -> None:
    last_error: Exception | None = None
    for attempt in range(1, 61):
        try:
            await _probe_reset_targets(settings)
            return
        except Exception as exc:  # readiness boundary for three external services
            last_error = exc
            if attempt < 60:
                await sleep(1)
    error_name = type(last_error).__name__ if last_error is not None else "unknown"
    raise RuntimeError(
        f"Isolated E2E reset targets did not become ready ({error_name})."
    ) from None


async def _probe_reset_targets(settings: Settings) -> None:
    engine = create_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    finally:
        await engine.dispose()

    redis = Redis.from_url(settings.redis_url)
    try:
        await redis.ping()
    finally:
        await redis.aclose()

    elasticsearch = create_elasticsearch(settings)
    try:
        await elasticsearch.cluster.health(
            wait_for_status="yellow",
            timeout="5s",
        )
    finally:
        await elasticsearch.close()


async def _reset_database(settings: Settings, tables: tuple[str, ...]) -> None:
    engine = create_engine(settings)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f"TRUNCATE TABLE {', '.join(tables)} "
                    "RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


async def _reset_redis(settings: Settings, database: int) -> None:
    client = Redis.from_url(settings.redis_url, db=database)
    try:
        await client.flushdb()
    finally:
        await client.aclose()


async def _reset_elasticsearch(settings: Settings, pattern: str) -> None:
    client = create_elasticsearch(settings)
    try:
        matches = await client.indices.get(
            index=pattern,
            allow_no_indices=True,
            expand_wildcards="all",
        )
        exact_names = sorted(matches)
        if exact_names:
            await client.indices.delete(
                index=exact_names,
                ignore_unavailable=True,
            )
    finally:
        await client.close()


def main() -> int:
    from ai_workshop.config import get_settings

    try:
        run(reset_e2e_state(get_settings(), environ))
    except E2ERuntimeContractError as exc:
        print(str(exc))
        return 2
    print("Isolated E2E database, Redis DB, and Elasticsearch prefix reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
