import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.engine import make_url

from ai_workshop.config import Settings

_SMOKE_PROJECT = re.compile(r"^ai-workshop-smoke(?:-[a-z0-9-]+)?$")
_SAFE_INSTRUCTION = "Prepared E2E state is required; run scripts/smoke.ps1."
RESET_DATABASE_TABLES = (
    "rag_profile_model_bindings",
    "rag_profiles",
    "rag_model_definitions",
    "jobs",
    "asset_versions",
    "documents",
    "folders",
    "workspace_memberships",
    "workspaces",
    "users",
)


class E2ERuntimeContractError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResetScope:
    project_name: str
    database_tables: tuple[str, ...]
    redis_database: int
    elasticsearch_index_pattern: str


def validate_prepared_e2e(
    settings: Settings, environment: Mapping[str, str]
) -> None:
    if settings.environment != "test" or environment.get(
        "AI_WORKSHOP_E2E_PREPARED"
    ) != "1":
        raise E2ERuntimeContractError(_SAFE_INSTRUCTION)
    _validate_isolated_targets(settings, environment)


def build_reset_scope(
    settings: Settings, environment: Mapping[str, str]
) -> ResetScope:
    validate_prepared_e2e(settings, environment)
    if environment.get("AI_WORKSHOP_E2E_RESET") != "1":
        raise E2ERuntimeContractError(_SAFE_INSTRUCTION)
    project_name = environment["AI_WORKSHOP_E2E_PROJECT"]
    redis = urlsplit(settings.redis_url)
    return ResetScope(
        project_name=project_name,
        database_tables=RESET_DATABASE_TABLES,
        redis_database=int(redis.path.removeprefix("/")),
        elasticsearch_index_pattern=f"{settings.elasticsearch_index_prefix}-*",
    )


def _validate_isolated_targets(
    settings: Settings, environment: Mapping[str, str]
) -> None:
    project_name = environment.get("AI_WORKSHOP_E2E_PROJECT", "")
    database = make_url(settings.database_url)
    redis = urlsplit(settings.redis_url)
    elasticsearch = urlsplit(settings.elasticsearch_url)
    if (
        _SMOKE_PROJECT.fullmatch(project_name) is None
        or database.host != "postgres"
        or database.port != 5432
        or database.database != "ai_workshop"
        or redis.scheme != "redis"
        or redis.hostname != "redis"
        or redis.port != 6379
        or redis.path != "/0"
        or redis.query
        or elasticsearch.scheme != "http"
        or elasticsearch.hostname != "elasticsearch"
        or elasticsearch.port != 9200
        or elasticsearch.path not in {"", "/"}
        or elasticsearch.query
        or settings.elasticsearch_index_prefix != f"{project_name}-rag"
    ):
        raise E2ERuntimeContractError(_SAFE_INSTRUCTION)
