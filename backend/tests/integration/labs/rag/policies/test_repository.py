from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import func, insert, select

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.policies.domain import (
    InstallationDataPolicyVersion,
    OutboundMode,
    WorkspaceDataPolicyVersion,
    WorkspaceOutboundMode,
)
from ai_workshop.labs.rag.policies.models import InstallationDataPolicyVersionRecord
from ai_workshop.labs.rag.policies.repository import SqlAlchemyDataPolicyRepository
from ai_workshop.platform.identity.models import UserRecord
from ai_workshop.platform.workspaces.models import WorkspaceRecord
from ai_workshop.shared.db import create_engine, create_session_factory
from alembic import command

pytestmark = pytest.mark.integration
BACKEND_ROOT = Path(__file__).resolve().parents[5]


@pytest.fixture(scope="module", autouse=True)
def migrated_database() -> None:
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "0016_rag_llm_deployments")


@pytest.mark.asyncio
async def test_installation_and_workspace_policy_versions_round_trip() -> None:
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    owner_id = uuid4()
    workspace_id = uuid4()
    now = datetime.now(UTC)
    try:
        async with sessions() as session:
            transaction = await session.begin()
            try:
                await session.execute(
                    insert(UserRecord).values(
                        id=owner_id,
                        display_name="Policy owner",
                        email=f"{owner_id}@example.test",
                        normalized_email=f"{owner_id}@example.test",
                        password_hash="fixture-hash",
                        role="owner",
                        is_active=True,
                    )
                )
                await session.execute(
                    insert(WorkspaceRecord).values(
                        id=workspace_id,
                        name=f"Synthetic workspace {workspace_id}",
                        kind="personal",
                        created_by=owner_id,
                        expires_at=None,
                    )
                )
                repository = SqlAlchemyDataPolicyRepository(session)
                policy_id = await repository.installation_policy_id()
                next_version = (
                    await session.scalar(
                        select(func.max(InstallationDataPolicyVersionRecord.version))
                    )
                    or 0
                ) + 1
                installation = InstallationDataPolicyVersion(
                    id=uuid4(),
                    policy_id=policy_id,
                    version=next_version,
                    mode=OutboundMode.APPROVED_PROVIDERS,
                    approved_providers=frozenset({ProviderKind.OPENAI_RESPONSES}),
                    changed_by=owner_id,
                    created_at=now,
                )
                workspace = WorkspaceDataPolicyVersion(
                    id=uuid4(),
                    policy_id=uuid4(),
                    workspace_id=workspace_id,
                    version=1,
                    mode=WorkspaceOutboundMode.APPROVED_PROVIDERS,
                    approved_providers=frozenset({ProviderKind.OPENAI_RESPONSES}),
                    changed_by=owner_id,
                    created_at=now,
                )

                assert await repository.add_installation_version(installation) == installation
                assert await repository.add_workspace_version(workspace) == workspace
                assert await repository.get_installation_version(installation.id) == installation
                assert await repository.get_workspace_version(workspace.id) == workspace
                assert await repository.latest_installation_policy() == installation
                assert await repository.latest_workspace_policies((workspace_id,)) == (
                    workspace,
                )
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
