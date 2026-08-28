from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.platform.workspaces.schemas import WorkspaceResponse


def owner() -> User:
    return User(
        id=uuid4(),
        display_name="Owner",
        email="owner@example.com",
        normalized_email="owner@example.com",
        password_hash="hash",
        role=UserRole.OWNER,
    )


def test_temporary_workspace_requires_future_expiry() -> None:
    with pytest.raises(ValueError, match="future expiry"):
        Workspace.create(
            name="Expired session",
            kind=WorkspaceKind.TEMPORARY,
            creator=owner(),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )


def test_personal_workspace_does_not_require_expiry() -> None:
    workspace = Workspace.create(
        name="My documents",
        kind=WorkspaceKind.PERSONAL,
        creator=owner(),
    )

    assert workspace.kind is WorkspaceKind.PERSONAL
    assert workspace.expires_at is None


def test_workspace_response_maps_slotted_domain_fields() -> None:
    workspace = Workspace.create(
        name="My documents",
        kind=WorkspaceKind.PERSONAL,
        creator=owner(),
    )

    response = WorkspaceResponse.from_domain(workspace)

    assert response.id == workspace.id
    assert response.name == "My documents"
    assert response.kind is WorkspaceKind.PERSONAL
