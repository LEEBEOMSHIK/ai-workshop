from collections.abc import Callable
from dataclasses import FrozenInstanceError
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.policies.domain import (
    DataPolicyValidationError,
    InstallationDataPolicyVersion,
    OutboundMode,
    PolicyDecision,
    PolicyReasonCode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
    resolve_external_transfer_policy,
)


def installation_policy(
    *,
    mode: OutboundMode = OutboundMode.APPROVED_PROVIDERS,
    providers: frozenset[ProviderKind] = frozenset({ProviderKind.OPENAI_RESPONSES}),
) -> InstallationDataPolicyVersion:
    if mode is OutboundMode.DENY:
        providers = frozenset()
    return InstallationDataPolicyVersion.create(
        policy_id=uuid4(),
        version=1,
        mode=mode,
        approved_providers=providers,
        changed_by=uuid4(),
    )


def workspace_policy(
    *,
    mode: WorkspaceOutboundMode = WorkspaceOutboundMode.INHERIT,
    providers: frozenset[ProviderKind] = frozenset(),
) -> WorkspaceDataPolicyVersion:
    return WorkspaceDataPolicyVersion.create(
        policy_id=uuid4(),
        workspace_id=uuid4(),
        version=1,
        mode=mode,
        approved_providers=providers,
        changed_by=uuid4(),
    )


def test_policy_versions_are_immutable_and_have_uuid_version_ids() -> None:
    installation = installation_policy()
    workspace = workspace_policy()

    assert isinstance(installation.id, UUID)
    assert isinstance(workspace.id, UUID)
    with pytest.raises(FrozenInstanceError):
        installation.version = 2


def test_workspace_policy_cannot_widen_installation_policy() -> None:
    installation = installation_policy(mode=OutboundMode.DENY)
    workspace = workspace_policy(
        mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
        providers=frozenset({ProviderKind.OPENAI_RESPONSES}),
    )

    with pytest.raises(DataPolicyValidationError, match="cannot widen"):
        resolve_external_transfer_policy(
            provider=ProviderKind.OPENAI_RESPONSES,
            installation=installation,
            workspaces=(workspace,),
        )


@pytest.mark.parametrize(
    ("installation", "workspaces", "reason_code"),
    [
        (
            installation_policy(mode=OutboundMode.DENY),
            (),
            "provider_not_allowed",
        ),
        (
            installation_policy(
                providers=frozenset({ProviderKind.LOCAL_OPENAI_COMPATIBLE})
            ),
            (),
            "provider_not_allowed",
        ),
        (
            installation_policy(),
            (workspace_policy(mode=WorkspaceOutboundMode.DENY),),
            "workspace_external_transfer_denied",
        ),
        (
            installation_policy(
                providers=frozenset(
                    {
                        ProviderKind.LOCAL_OPENAI_COMPATIBLE,
                        ProviderKind.OPENAI_RESPONSES,
                    }
                )
            ),
            (
                workspace_policy(
                    mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
                    providers=frozenset({ProviderKind.LOCAL_OPENAI_COMPATIBLE}),
                ),
            ),
            "workspace_external_transfer_denied",
        ),
    ],
)
def test_external_policy_denials_use_approved_scope_reason_codes(
    installation: InstallationDataPolicyVersion,
    workspaces: tuple[WorkspaceDataPolicyVersion, ...],
    reason_code: str,
) -> None:
    decision = resolve_external_transfer_policy(
        provider=ProviderKind.OPENAI_RESPONSES,
        installation=installation,
        workspaces=workspaces,
    )

    assert decision.allowed is False
    assert decision.reason_code == reason_code
    assert decision.installation_policy_version_id == installation.id
    assert decision.workspace_policy_version_ids == tuple(policy.id for policy in workspaces)


def test_all_selected_workspaces_must_allow_the_external_provider() -> None:
    first = workspace_policy()
    second = workspace_policy(
        mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
        providers=frozenset({ProviderKind.OPENAI_RESPONSES}),
    )

    decision = resolve_external_transfer_policy(
        provider=ProviderKind.OPENAI_RESPONSES,
        installation=installation_policy(),
        workspaces=(first, second),
    )

    assert decision.allowed is True
    assert decision.reason_code is None
    assert decision.workspace_policy_version_ids == (first.id, second.id)


def test_local_provider_is_not_blocked_by_outbound_policy() -> None:
    decision = resolve_external_transfer_policy(
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        installation=installation_policy(mode=OutboundMode.DENY),
        workspaces=(workspace_policy(mode=WorkspaceOutboundMode.DENY),),
    )

    assert decision.allowed is True
    assert decision.reason_code is None


def test_policy_reason_codes_are_typed_and_string_compatible() -> None:
    installation = installation_policy(mode=OutboundMode.DENY)

    decision = resolve_external_transfer_policy(
        provider=ProviderKind.OPENAI_RESPONSES,
        installation=installation,
        workspaces=(),
    )

    assert decision.reason_code is PolicyReasonCode.PROVIDER_NOT_ALLOWED
    assert decision.reason_code == "provider_not_allowed"


def test_policy_decision_rejects_an_arbitrary_reason_code() -> None:
    with pytest.raises(DataPolicyValidationError, match="reason code"):
        PolicyDecision(
            allowed=False,
            reason_code="arbitrary_public_code",
            installation_policy_version_id=uuid4(),
            workspace_policy_version_ids=(),
        )


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: InstallationDataPolicyVersion.create(
                policy_id=uuid4(),
                version=0,
                mode=OutboundMode.DENY,
                approved_providers=frozenset(),
                changed_by=uuid4(),
            ),
            "version",
        ),
        (
            lambda: InstallationDataPolicyVersion.create(
                policy_id=uuid4(),
                version=1,
                mode=OutboundMode.APPROVED_PROVIDERS,
                approved_providers=frozenset(),
                changed_by=uuid4(),
            ),
            "approved Provider",
        ),
        (
            lambda: WorkspaceDataPolicyVersion.create(
                policy_id=uuid4(),
                workspace_id=uuid4(),
                version=1,
                mode=WorkspaceOutboundMode.INHERIT,
                approved_providers=frozenset({ProviderKind.OPENAI_RESPONSES}),
                changed_by=uuid4(),
            ),
            "only use approved Providers",
        ),
    ],
)
def test_policy_versions_reject_invalid_shapes(
    factory: Callable[[], object], message: str
) -> None:
    with pytest.raises(DataPolicyValidationError, match=message):
        factory()


def test_policy_versions_require_named_modes() -> None:
    with pytest.raises(DataPolicyValidationError, match="mode"):
        InstallationDataPolicyVersion.create(
            policy_id=uuid4(),
            version=1,
            mode="deny",
            approved_providers=frozenset(),
            changed_by=uuid4(),
        )
