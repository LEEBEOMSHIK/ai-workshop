from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.configurations.models import (
    RagSystemIndexingSubscriptionRecord,
)
from ai_workshop.labs.rag.configurations.repository import (
    SqlAlchemyRagConfigurationRepository,
)


def test_system_indexing_subscription_references_exact_configuration_version() -> None:
    table = RagSystemIndexingSubscriptionRecord.__table__

    assert table.name == "rag_system_indexing_subscriptions"
    assert set(table.columns.keys()) == {
        "configuration_version_id",
        "id",
        "created_at",
        "updated_at",
    }
    assert table.columns.configuration_version_id.unique is True


class _Rows:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[object, object]]:
        return self._rows


class _Session:
    def __init__(self, *rows: list[tuple[object, object]]) -> None:
        self._rows = iter(rows)
        self.statements: list[str] = []

    async def execute(self, statement: object) -> _Rows:
        self.statements.append(str(statement))
        return _Rows(next(self._rows))


@pytest.mark.asyncio
async def test_system_and_user_demand_collapse_to_one_asset_profile_command() -> None:
    baseline_profile = uuid4()
    other_profile = uuid4()
    workspace_creator = uuid4()
    saved_configuration_owner = uuid4()
    session = _Session(
        [(baseline_profile, workspace_creator)],
        [
            (baseline_profile, saved_configuration_owner),
            (other_profile, saved_configuration_owner),
        ],
    )
    repository = SqlAlchemyRagConfigurationRepository(
        cast(AsyncSession, cast(Any, session))
    )

    subscriptions = await repository.subscriptions_for_asset(uuid4())

    assert subscriptions == (
        (baseline_profile, workspace_creator),
        (other_profile, saved_configuration_owner),
    )
    assert "rag_system_indexing_subscriptions" in session.statements[0]
    assert "rag_configuration_workspace_subscriptions" in session.statements[1]
