from uuid import UUID

import pytest

from ai_workshop.config import Settings
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.setup.service import SystemSetupService
from ai_workshop.platform.workspaces.domain import Workspace, WorkspaceKind
from ai_workshop.platform.workspaces.service import WorkspaceService
from ai_workshop.shared.errors import AppError


class MemoryOwnerSetupRepository:
    def __init__(self, owner: User | None = None) -> None:
        self.owner = owner
        self.locked = False

    async def lock_owner_setup(self) -> None:
        self.locked = True

    async def owner_exists(self) -> bool:
        return self.owner is not None

    async def add(self, user: User) -> User:
        assert self.locked
        self.owner = user
        return user


class MemoryWorkspaceRepository:
    def __init__(self) -> None:
        self.workspaces: list[Workspace] = []

    async def list_for_user(self, user_id: UUID) -> list[Workspace]:
        return [item for item in self.workspaces if item.created_by == user_id]

    async def has_personal(self, user_id: UUID) -> bool:
        return any(
            item.created_by == user_id and item.kind is WorkspaceKind.PERSONAL
            for item in self.workspaces
        )

    async def add(self, workspace: Workspace, owner_id: UUID) -> Workspace:
        assert workspace.created_by == owner_id
        self.workspaces.append(workspace)
        return workspace


class RecordingPasswordHasher:
    def hash(self, password: str) -> str:
        return f"hashed::{password}"

    def verify(self, password: str, password_hash: str) -> bool:
        return password_hash == f"hashed::{password}"


class RecordingTokens:
    def create(self, user: User) -> str:
        return f"session::{user.id}"


def local_settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="local",
        secret_key="x" * 32,
        setup_company_workspace_name="전사 자산운용 지식",
        setup_personal_workspace_name="개인 연구",
    )


@pytest.mark.asyncio
async def test_setup_creates_one_owner_and_both_default_workspaces() -> None:
    users = MemoryOwnerSetupRepository()
    workspaces = MemoryWorkspaceRepository()
    service = SystemSetupService(
        users,
        WorkspaceService(workspaces),
        RecordingPasswordHasher(),
        RecordingTokens(),
        local_settings(),
    )

    owner, token = await service.create_owner(
        display_name="LEE BEOMSHIK",
        email="bumcity135@naver.com",
        password="correct-password",
        password_confirmation="correct-password",
    )

    assert users.locked is True
    assert users.owner == owner
    assert owner.password_hash == "hashed::correct-password"
    assert token == f"session::{owner.id}"
    assert [(item.name, item.kind) for item in workspaces.workspaces] == [
        ("전사 자산운용 지식", WorkspaceKind.COMPANY),
        ("개인 연구", WorkspaceKind.PERSONAL),
    ]


@pytest.mark.asyncio
async def test_setup_rejects_a_second_owner_after_acquiring_the_setup_lock() -> None:
    existing = User.create_owner(
        display_name="Existing Owner",
        email="existing@example.com",
        password_hash="hash",
    )
    users = MemoryOwnerSetupRepository(existing)
    service = SystemSetupService(
        users,
        WorkspaceService(MemoryWorkspaceRepository()),
        RecordingPasswordHasher(),
        RecordingTokens(),
        local_settings(),
    )

    with pytest.raises(AppError) as exc_info:
        await service.create_owner(
            display_name="Another Owner",
            email="another@example.com",
            password="correct-password",
            password_confirmation="correct-password",
        )

    assert users.locked is True
    assert exc_info.value.code == "setup_already_completed"
    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_setup_rejects_mismatched_password_confirmation_before_locking() -> None:
    users = MemoryOwnerSetupRepository()
    service = SystemSetupService(
        users,
        WorkspaceService(MemoryWorkspaceRepository()),
        RecordingPasswordHasher(),
        RecordingTokens(),
        local_settings(),
    )

    with pytest.raises(AppError) as exc_info:
        await service.create_owner(
            display_name="LEE BEOMSHIK",
            email="bumcity135@naver.com",
            password="correct-password",
            password_confirmation="different-password",
        )

    assert users.locked is False
    assert exc_info.value.code == "password_confirmation_mismatch"
