from uuid import uuid4

import pytest

from ai_workshop.labs.rag.evaluation.tasks import FrozenResolvedScope
from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope


@pytest.mark.asyncio
async def test_frozen_scope_preserves_exact_snapshot_ids_and_inactive_semantics() -> None:
    indexing_profile_id = uuid4()
    frozen = ResolvedSearchScope(
        workspace_ids=(uuid4(),),
        folder_ids=(uuid4(),),
        active_only=False,
        ready_only=True,
        asset_version_ids=(uuid4(), uuid4()),
        index_build_ids=(uuid4(), uuid4()),
    )

    resolved = await FrozenResolvedScope(frozen).resolve(
        actor_id=uuid4(),
        workspace_ids=frozen.workspace_ids,
        folder_ids=frozen.folder_ids,
        indexing_profile_id=indexing_profile_id,
    )

    assert resolved is frozen
    assert resolved.active_only is False
    assert resolved.asset_version_ids == frozen.asset_version_ids
    assert resolved.index_build_ids == frozen.index_build_ids
