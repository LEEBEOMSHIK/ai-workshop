from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from ai_workshop.labs.rag.conversations.access import ConversationAccess, source_identities


def test_all_nested_sources_including_diagnostics_are_dependencies():
    ids = [uuid4() for _ in range(3)]
    source = dict(
        zip(("document_id", "asset_version_id", "projection_id"), map(str, ids), strict=True)
    )
    assert source_identities({"diagnostics": {"candidates": [{"source": source}]}}) == {tuple(ids)}


@pytest.mark.asyncio
async def test_failed_turn_selected_document_is_revalidated():
    workspace, document = uuid4(), uuid4()
    db = SimpleNamespace(
        scalars=AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: [workspace]),
                SimpleNamespace(all=lambda: []),
            ]
        )
    )

    @asynccontextmanager
    async def sessions():
        yield db

    turn = SimpleNamespace(
        response=None, request={"workspace_ids": [str(workspace)], "document_ids": [str(document)]}
    )
    assert not await ConversationAccess(sessions).visible(uuid4(), turn)
    sql = str(db.scalars.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "documents.lifecycle" in sql and "workspace_memberships" in sql
    assert "users.is_active" in sql and "documents.workspace_id IN" in sql


@pytest.mark.asyncio
async def test_revoked_external_approval_blocks_history_sources():
    workspace, document, version, projection = [uuid4() for _ in range(4)]
    db = SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [workspace])),
        scalar=AsyncMock(side_effect=[document, None]),
    )

    @asynccontextmanager
    async def sessions():
        yield db

    turn = SimpleNamespace(
        request={"workspace_ids": [str(workspace)]},
        response={
            "source": {
                "document_id": str(document),
                "asset_version_id": str(version),
                "projection_id": str(projection),
            },
        },
    )
    assert not await ConversationAccess(sessions).visible(uuid4(), turn, external=True)
    source_sql = str(db.scalar.call_args_list[0].args[0].compile(dialect=postgresql.dialect()))
    # A new active version opens a new segment, but does not erase an authorized
    # historical source version from the saved transcript.
    assert "documents.active_version_id" not in source_sql
    assert "documents.lifecycle" in source_sql
    sql = str(db.scalar.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert "rag_evidence_approval_states.revoked_at IS NULL" in sql
    assert "rag_evidence_approval_states.content_sha256 = asset_versions.sha256" in sql
