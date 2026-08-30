from uuid import uuid4

import pytest

from ai_workshop.labs.rag.documents.domain import (
    InvalidProjectionTransition,
    ProjectionStatus,
    RagProjection,
)


def test_projection_follows_the_required_stages_before_ready() -> None:
    projection = RagProjection.pending(asset_version_id=uuid4(), indexing_profile_id=uuid4())

    for status in (
        ProjectionStatus.PARSING,
        ProjectionStatus.CHUNKING,
        ProjectionStatus.EMBEDDING,
        ProjectionStatus.INDEXING,
        ProjectionStatus.READY,
    ):
        projection = projection.transition(status)

    assert projection.status is ProjectionStatus.READY


def test_projection_rejects_ready_before_indexing_verification_stage() -> None:
    projection = RagProjection.pending(asset_version_id=uuid4(), indexing_profile_id=uuid4())

    with pytest.raises(InvalidProjectionTransition):
        projection.transition(ProjectionStatus.READY)


def test_failed_projection_is_terminal() -> None:
    projection = RagProjection.pending(asset_version_id=uuid4(), indexing_profile_id=uuid4())
    failed = projection.transition(ProjectionStatus.FAILED)

    with pytest.raises(InvalidProjectionTransition):
        failed.transition(ProjectionStatus.PARSING)
