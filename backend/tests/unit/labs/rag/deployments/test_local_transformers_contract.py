from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    DeploymentValidationError,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.repository import (
    DeploymentCatalogEntry,
    _version_domain,
    _version_record,
)
from ai_workshop.labs.rag.deployments.schemas import (
    DeploymentAdminResponse,
    DeploymentOptionResponse,
    DeploymentVersionCreate,
)
from ai_workshop.labs.rag.policies.domain import (
    DataPolicyValidationError,
    InstallationDataPolicyVersion,
    OutboundMode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
    resolve_external_transfer_policy,
)


def local_deployment() -> ModelDeploymentVersion:
    return ModelDeploymentVersion.create(
        deployment_id=uuid4(), version=1, display_name="Local text generation",
        description="Synthetic test", model_definition_id=uuid4(),
        provider=ProviderKind("local_transformers"), location=ExecutionLocation.LOCAL,
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        provider_model_id="example/model", endpoint_ref=None, secret_ref=None,
        local_model_ref="local-text-v1", capabilities=(DeploymentCapability.STRUCTURED_OUTPUT,),
        external_transfer=False, transmitted_data_categories=(),
        data_processing_notice_ref=None, timeout_seconds=30, max_retries=0,
        retry_backoff_seconds=0, healthcheck_enabled=True, development_only=False,
        created_by=uuid4(),
    )


def test_local_reference_roundtrips_storage_and_public_metadata() -> None:
    deployment = local_deployment()
    restored = _version_domain(_version_record(deployment))
    assert restored == deployment
    assert restored.endpoint_ref is None
    entry = DeploymentCatalogEntry(restored, "Local test", 1)
    admin = DeploymentAdminResponse.from_entry(entry, secret_configured=False)
    option = DeploymentOptionResponse.from_entry(entry)
    assert admin.local_model_ref == option.local_model_ref == "local-text-v1"
    assert option.approval.required is False
    request = DeploymentVersionCreate(
        display_name=deployment.display_name, model_definition_id=deployment.model_definition_id,
        provider=deployment.provider, location=deployment.location,
        allowed_environments=list(deployment.allowed_environments),
        provider_model_id=deployment.provider_model_id, endpoint_ref=None,
        local_model_ref=deployment.local_model_ref, capabilities=set(deployment.capabilities),
        external_transfer=False, timeout_seconds=30, max_retries=0,
        retry_backoff_seconds=0, healthcheck_enabled=True, development_only=False,
    )
    assert request.local_model_ref == "local-text-v1"


@pytest.mark.parametrize("overrides", [
    {"local_model_ref": None}, {"local_model_ref": ""},
    {"local_model_ref": "C:/models/snapshot"}, {"local_model_ref": "https://example.test"},
    {"local_model_ref": "secret-token"}, {"local_model_ref": "a-" + "x" * 120},
    {"endpoint_ref": "local-http"}, {"runner_ref": "local-runner"},
    {"secret_ref": "local-secret"}, {"external_transfer": True},
    {"location": ExecutionLocation.EXTERNAL}, {"max_retries": 1},
    {"retry_backoff_seconds": 1}, {"transmitted_data_categories": ("question",)},
    {"data_processing_notice_ref": "external-notice"},
])
def test_local_rejects_network_secret_and_retry_contracts(overrides: dict[str, object]) -> None:
    with pytest.raises(DeploymentValidationError):
        replace(local_deployment(), **overrides)


def test_http_cannot_hold_a_local_model_reference() -> None:
    with pytest.raises(DeploymentValidationError):
        replace(local_deployment(), provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
                endpoint_ref="local-http")


def test_local_policy_respects_configuration_integrity_without_external_approval() -> None:
    installation = InstallationDataPolicyVersion.create(
        policy_id=uuid4(), version=1, mode=OutboundMode.DENY,
        approved_providers=(), changed_by=uuid4(),
    )
    workspace = WorkspaceDataPolicyVersion.create(
        policy_id=uuid4(), workspace_id=uuid4(), version=1, mode=WorkspaceOutboundMode.DENY,
        approved_providers=(), changed_by=uuid4(),
    )
    provider = local_deployment().provider
    assert resolve_external_transfer_policy(
        provider=provider, installation=installation, workspaces=(workspace,),
    ).allowed
    invalid_workspace = replace(workspace, mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
                                approved_providers=frozenset({ProviderKind.OPENAI_RESPONSES}))
    with pytest.raises(DataPolicyValidationError):
        resolve_external_transfer_policy(
            provider=provider, installation=installation, workspaces=(invalid_workspace,),
        )
