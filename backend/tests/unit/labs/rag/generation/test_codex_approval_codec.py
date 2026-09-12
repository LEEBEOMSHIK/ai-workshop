from copy import deepcopy
from dataclasses import replace
from importlib import import_module
from uuid import UUID

import pytest

from tests.unit.labs.rag.generation.test_codex_authorization import _intent


def _codec():
    try:
        return import_module("ai_workshop.labs.rag.generation.codex_approval_codec")
    except ModuleNotFoundError:
        pytest.fail("The exact approval binding codec is not implemented")


def test_round_trip_canonicalizes_uuid_arrays_without_losing_binding():
    codec = _codec()
    intent = _intent()
    unordered = replace(
        intent,
        workspace_ids=tuple(reversed(intent.workspace_ids)),
        evidence_revisions=tuple(reversed(intent.evidence_revisions)),
        workspace_policy_bindings=tuple(reversed(intent.workspace_policy_bindings)),
    )
    encoded = codec.encode_intent(unordered)
    assert encoded["version"] == 3
    assert encoded["workspace_ids"] == [str(UUID(int=10)), str(UUID(int=11))]
    assert codec.decode_intent(encoded) == intent


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", True),
        ("version", 1.0),
        ("version", 1),
        ("version", 2),
        ("version", "1"),
        ("actor_id", 1),
        ("operation", "shell"),
        ("stage", "shell"),
        ("runner_ref", "../secret"),
        ("runner_ref", "token-sensitive"),
        ("provider_model_id", ""),
        ("provider_model_id", True),
        ("generation_disclosure_version", " "),
        ("output_schema_sha256", "A" * 64),
        ("runner_configuration_sha256", "A" * 64),
        ("workspace_ids", [True]),
        ("question", "do not persist input"),
    ],
)
def test_rejects_invalid_or_unknown_top_level_fields(field, value):
    codec = _codec()
    encoded = codec.encode_intent(_intent())
    encoded[field] = value
    with pytest.raises(ValueError, match="invalid_codex_approval_binding"):
        codec.decode_intent(encoded)


@pytest.mark.parametrize(
    "field,key,value",
    [
        ("workspace_policy_bindings", "policy_version_id", False),
        ("workspace_policy_bindings", "unknown", "private input"),
        ("evidence_revisions", "content_sha256", "bad"),
        ("evidence_revisions", "revision_id", 1),
        ("evidence_revisions", "body", "private input"),
        ("evidence_revisions", "approval_generation", 0),
        ("evidence_revisions", "approval_generation", True),
    ],
)
def test_rejects_nested_coercion_and_unknown_content(field, key, value):
    codec = _codec()
    encoded = deepcopy(codec.encode_intent(_intent()))
    encoded[field][0][key] = value
    with pytest.raises(ValueError, match="invalid_codex_approval_binding"):
        codec.decode_intent(encoded)


@pytest.mark.parametrize(
    "field", ["workspace_ids", "workspace_policy_bindings", "evidence_revisions"]
)
def test_rejects_duplicate_identifiers(field):
    codec = _codec()
    encoded = codec.encode_intent(_intent())
    encoded[field].append(deepcopy(encoded[field][0]))
    with pytest.raises(ValueError):
        codec.decode_intent(encoded)


def test_rejects_missing_scope_binding_and_arbitrary_encoding_input():
    codec = _codec()
    encoded = codec.encode_intent(_intent())
    encoded["workspace_policy_bindings"].pop()
    with pytest.raises(ValueError):
        codec.decode_intent(encoded)
    with pytest.raises(ValueError):
        codec.encode_intent({"question": "private input"})


def test_binding_requires_exact_runner_fingerprint():
    codec = _codec()
    encoded = codec.encode_intent(_intent())
    assert encoded.get("runner_configuration_sha256") == "c" * 64
    del encoded["runner_configuration_sha256"]
    with pytest.raises(ValueError):
        codec.decode_intent(encoded)


@pytest.mark.parametrize("field,value", [("actor_id", str(UUID(int=1))), ("operation", "search")])
def test_encoding_rejects_non_typed_intent_values(field, value):
    codec = _codec()
    with pytest.raises(ValueError):
        codec.encode_intent(replace(_intent(), **{field: value}))


@pytest.mark.parametrize("after_yield", [False, True])
async def test_source_failure_does_not_retain_raw_database_exception(after_yield):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
    from ai_workshop.labs.rag.generation.codex_approval_repository import (
        SqlAlchemyCodexAuthorizationSource,
    )
    from ai_workshop.labs.rag.generation.codex_authorization import CodexAuthorizationError

    class FailingSession(AsyncSession):
        async def connection(self, *args, **kwargs):
            # No external connection: the failure being exercised is the SQL boundary.
            return None

        async def execute(self, *args, **kwargs):
            if after_yield:
                return None
            raise RuntimeError("raw SQL with sensitive-bound-value")

        async def scalar(self, *args, **kwargs):
            # First repository lookup executes inside the yielded transaction body.
            raise RuntimeError("raw SQL with sensitive-bound-value")

    first = create_async_engine("postgresql+psycopg://unused/never_connected")
    second = create_async_engine("postgresql+psycopg://unused/never_connected")
    source = SqlAlchemyCodexAuthorizationSource(
        async_sessionmaker(first, class_=FailingSession),
        consumption_engine=second,
        environment=DeploymentEnvironment.DEVELOPMENT,
    )
    try:
        with pytest.raises(CodexAuthorizationError) as error:
            await source.revoke_call(actor_id=UUID(int=1), approval_id=UUID(int=2))
        assert error.value.__context__ is None
        assert error.value.__cause__ is None
        assert "sensitive-bound-value" not in str(error.value)
    finally:
        await first.dispose()
        await second.dispose()


async def test_source_requires_separate_pools_and_locked_exact_consumption():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from ai_workshop.labs.rag.deployments.domain import DeploymentEnvironment
    from ai_workshop.labs.rag.generation.codex_approval_repository import (
        SqlAlchemyCodexAuthorizationSource,
    )
    from ai_workshop.labs.rag.generation.codex_authorization import (
        CodexAuthorizationError,
        CodexAuthorizationErrorCode,
        CodexCallStage,
    )

    first = create_async_engine("postgresql+psycopg://unused/never_connected")
    second = create_async_engine("postgresql+psycopg://unused/never_connected")
    try:
        with pytest.raises(ValueError, match="distinct_pools"):
            SqlAlchemyCodexAuthorizationSource(
                async_sessionmaker(first),
                consumption_engine=first,
                environment=DeploymentEnvironment.DEVELOPMENT,
            )
        with pytest.raises(ValueError, match="distinct_pools"):
            SqlAlchemyCodexAuthorizationSource(
                async_sessionmaker(first),
                consumption_engine=first.execution_options(isolation_level="READ COMMITTED"),
                environment=DeploymentEnvironment.DEVELOPMENT,
            )
        source = SqlAlchemyCodexAuthorizationSource(
            async_sessionmaker(first),
            consumption_engine=second,
            environment=DeploymentEnvironment.DEVELOPMENT,
        )
        with pytest.raises(CodexAuthorizationError) as error:
            await source.consume(UUID(int=1), UUID(int=2), CodexCallStage.GENERATE)
        assert error.value.code is CodexAuthorizationErrorCode.INVALID_INTENT
    finally:
        await first.dispose()
        await second.dispose()
