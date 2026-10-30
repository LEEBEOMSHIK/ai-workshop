from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from ai_workshop.config import Settings
from ai_workshop.labs.rag.generation.readiness import SqlAlchemyGenerationReadiness
from tests.unit.labs.rag.configurations.test_configuration import (
    _saved_external_configuration_for_readiness,
)


async def test_readiness_batches_immutable_inputs_but_rechecks_approvals_each_call():
    configuration, repository, service, _readiness = (
        await _saved_external_configuration_for_readiness()
    )
    configurations = tuple(
        replace(configuration, version_id=uuid4()) for _ in range(16)
    )
    repository.approvals = [
        replace(repository.approvals[0], configuration_version_id=item.version_id)
        for item in configurations
    ]
    repository.find_profiles = AsyncMock(return_value=repository.profiles)
    repository.get_deployment_versions = AsyncMock(return_value=repository.deployments)
    repository.get_model_definitions = AsyncMock(return_value=repository.models)
    repository.find_profile = AsyncMock(side_effect=AssertionError("unbatched profile read"))
    repository.get_deployment_version = AsyncMock(
        side_effect=AssertionError("unbatched deployment")
    )
    repository.get_model_definition = AsyncMock(side_effect=AssertionError("unbatched model"))

    first = await service.readiness(configurations)
    assert all(item.answer_ready and item.service_ready for item in first.values())
    repository.find_profiles.assert_awaited_once()
    repository.get_deployment_versions.assert_awaited_once()
    repository.get_model_definitions.assert_awaited_once()
    repository.approvals.clear()
    second = await service.readiness(configurations)
    assert all(not item.answer_ready for item in second.values())
    assert repository.find_profiles.await_count == 2


async def test_resolved_readiness_retains_current_health_checks_without_duplicate_inputs():
    configuration, repository, service, _readiness = (
        await _saved_external_configuration_for_readiness()
    )
    deployment = next(iter(repository.deployments.values()))
    readiness = SqlAlchemyGenerationReadiness(
        object(), Settings(secret_key="x" * 32, _env_file=None),
    )
    readiness.profiles = SimpleNamespace(
        find_profile=AsyncMock(side_effect=AssertionError("duplicate profile read")),
    )
    health = SimpleNamespace(
        status="ready", safe_error_code=None,
        observed_provider_model_id=deployment.provider_model_id,
    )
    readiness.deployments = SimpleNamespace(
        get_version=AsyncMock(side_effect=AssertionError("duplicate deployment read")),
        latest_health_check=AsyncMock(return_value=health),
    )
    service.generation_readiness = readiness
    first = await service.readiness((configuration,))
    assert first[configuration.version_id].answer_ready
    health.status = "failed"
    second = await service.readiness((configuration,))
    assert not second[configuration.version_id].answer_ready
    assert readiness.deployments.latest_health_check.await_count == 2
