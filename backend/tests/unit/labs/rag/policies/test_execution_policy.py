from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    OutboundMode,
    PolicyReasonCode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
)
from ai_workshop.labs.rag.policies.service import GenerationPolicyResolver


class MemoryPolicyReader:
    def __init__(
        self,
        installation: InstallationDataPolicyVersion,
        workspaces: tuple[WorkspaceDataPolicyVersion, ...],
    ) -> None:
        self.installation = installation
        self.workspaces = {policy.workspace_id: policy for policy in workspaces}

    async def latest_installation_policy(self) -> InstallationDataPolicyVersion:
        return self.installation

    async def latest_workspace_policies(
        self, workspace_ids: tuple[UUID, ...]
    ) -> tuple[WorkspaceDataPolicyVersion, ...]:
        return tuple(
            self.workspaces[workspace_id]
            for workspace_id in workspace_ids
            if workspace_id in self.workspaces
        )


def installation_policy(
    *,
    mode: OutboundMode = OutboundMode.APPROVED_PROVIDERS,
    providers: frozenset[ProviderKind] = frozenset(
        {ProviderKind.OPENAI_RESPONSES}
    ),
    version: int = 1,
) -> InstallationDataPolicyVersion:
    if mode is OutboundMode.DENY:
        providers = frozenset()
    return InstallationDataPolicyVersion.create(
        policy_id=uuid4(),
        version=version,
        mode=mode,
        approved_providers=providers,
        changed_by=uuid4(),
    )


def workspace_policy(
    workspace_id: UUID,
    *,
    mode: WorkspaceOutboundMode = WorkspaceOutboundMode.INHERIT,
    providers: frozenset[ProviderKind] = frozenset(),
    version: int = 1,
) -> WorkspaceDataPolicyVersion:
    return WorkspaceDataPolicyVersion.create(
        policy_id=uuid4(),
        workspace_id=workspace_id,
        version=version,
        mode=mode,
        approved_providers=providers,
        changed_by=uuid4(),
    )


def deployment(location: ExecutionLocation) -> ModelDeploymentVersion:
    external = location is ExecutionLocation.EXTERNAL
    return ModelDeploymentVersion.create(
        deployment_id=uuid4(),
        version=1,
        display_name="Synthetic deployment",
        description="",
        model_definition_id=uuid4(),
        provider=(
            ProviderKind.OPENAI_RESPONSES
            if external
            else ProviderKind.LOCAL_OPENAI_COMPATIBLE
        ),
        location=location,
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        provider_model_id="synthetic-model",
        endpoint_ref="synthetic-endpoint",
        secret_ref="synthetic-secret" if external else None,
        capabilities=(DeploymentCapability.STRUCTURED_OUTPUT,),
        external_transfer=external,
        transmitted_data_categories=("question",) if external else (),
        data_processing_notice_ref="public-notice-v1" if external else None,
        timeout_seconds=10,
        max_retries=0,
        retry_backoff_seconds=0,
        healthcheck_enabled=False,
        development_only=False,
        created_by=uuid4(),
    )


@pytest.mark.asyncio
async def test_any_denied_workspace_blocks_the_whole_external_generation() -> None:
    allowed_id = uuid4()
    denied_id = uuid4()
    allowed = workspace_policy(allowed_id)
    denied = workspace_policy(denied_id, mode=WorkspaceOutboundMode.DENY)
    resolver = GenerationPolicyResolver(
        MemoryPolicyReader(installation_policy(), (allowed, denied))
    )

    decision = await resolver.resolve(
        deployment=deployment(ExecutionLocation.EXTERNAL),
        workspace_ids=(allowed_id, denied_id),
    )

    assert decision.allowed is False
    assert decision.reason_code is PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED
    assert decision.workspace_policy_version_ids == (allowed.id, denied.id)


@pytest.mark.asyncio
async def test_missing_requested_workspace_policy_fails_external_closed() -> None:
    existing_id = uuid4()
    missing_id = uuid4()
    existing = workspace_policy(existing_id)
    resolver = GenerationPolicyResolver(
        MemoryPolicyReader(installation_policy(), (existing,))
    )

    decision = await resolver.resolve(
        deployment=deployment(ExecutionLocation.EXTERNAL),
        workspace_ids=(existing_id, missing_id),
    )

    assert decision.allowed is False
    assert decision.reason_code is PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED
    assert decision.workspace_policy_version_ids == (existing.id,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "installation",
    [
        installation_policy(mode=OutboundMode.DENY),
        installation_policy(
            providers=frozenset({ProviderKind.LOCAL_OPENAI_COMPATIBLE})
        ),
    ],
)
async def test_installation_must_approve_the_external_provider(
    installation: InstallationDataPolicyVersion,
) -> None:
    workspace_id = uuid4()
    policy = workspace_policy(workspace_id)
    resolver = GenerationPolicyResolver(MemoryPolicyReader(installation, (policy,)))

    decision = await resolver.resolve(
        deployment=deployment(ExecutionLocation.EXTERNAL),
        workspace_ids=(workspace_id,),
    )

    assert decision.allowed is False
    assert decision.reason_code is PolicyReasonCode.PROVIDER_NOT_ALLOWED
    assert decision.installation_policy_version_id == installation.id


@pytest.mark.asyncio
async def test_workspace_must_approve_the_external_provider() -> None:
    workspace_id = uuid4()
    installation = installation_policy(
        providers=frozenset(
            {
                ProviderKind.LOCAL_OPENAI_COMPATIBLE,
                ProviderKind.OPENAI_RESPONSES,
            }
        )
    )
    policy = workspace_policy(
        workspace_id,
        mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
        providers=frozenset({ProviderKind.LOCAL_OPENAI_COMPATIBLE}),
    )
    resolver = GenerationPolicyResolver(MemoryPolicyReader(installation, (policy,)))

    decision = await resolver.resolve(
        deployment=deployment(ExecutionLocation.EXTERNAL),
        workspace_ids=(workspace_id,),
    )

    assert decision.allowed is False
    assert decision.reason_code is PolicyReasonCode.WORKSPACE_EXTERNAL_TRANSFER_DENIED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "location", [ExecutionLocation.LOCAL, ExecutionLocation.ON_PREMISE]
)
async def test_local_and_on_premise_ignore_outbound_policy_but_return_audit_ids(
    location: ExecutionLocation,
) -> None:
    existing_id = uuid4()
    missing_id = uuid4()
    installation = installation_policy(mode=OutboundMode.DENY)
    existing = workspace_policy(
        existing_id,
        mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
        providers=frozenset({ProviderKind.OPENAI_RESPONSES}),
    )
    resolver = GenerationPolicyResolver(MemoryPolicyReader(installation, (existing,)))

    decision = await resolver.resolve(
        deployment=deployment(location),
        workspace_ids=(existing_id, missing_id),
    )

    assert decision.allowed is True
    assert decision.reason_code is None
    assert decision.installation_policy_version_id == installation.id
    assert decision.workspace_policy_version_ids == (existing.id,)


@pytest.mark.asyncio
async def test_resolver_loads_exact_latest_versions_for_each_decision() -> None:
    workspace_id = uuid4()
    initial_installation = installation_policy(version=1)
    initial_workspace = workspace_policy(workspace_id, version=1)
    repository = MemoryPolicyReader(initial_installation, (initial_workspace,))
    resolver = GenerationPolicyResolver(repository)
    first = await resolver.resolve(
        deployment=deployment(ExecutionLocation.EXTERNAL),
        workspace_ids=(workspace_id,),
    )

    repository.installation = replace(
        initial_installation, id=uuid4(), version=2
    )
    repository.workspaces[workspace_id] = replace(
        initial_workspace,
        id=uuid4(),
        version=2,
        mode=WorkspaceOutboundMode.DENY,
    )
    second = await resolver.resolve(
        deployment=deployment(ExecutionLocation.EXTERNAL),
        workspace_ids=(workspace_id,),
    )

    assert first.allowed is True
    assert first.installation_policy_version_id == initial_installation.id
    assert first.workspace_policy_version_ids == (initial_workspace.id,)
    assert second.allowed is False
    assert second.installation_policy_version_id == repository.installation.id
    assert second.workspace_policy_version_ids == (
        repository.workspaces[workspace_id].id,
    )
