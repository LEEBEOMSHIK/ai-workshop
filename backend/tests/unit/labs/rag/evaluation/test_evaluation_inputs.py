from uuid import uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
)
from ai_workshop.labs.rag.evaluation.service import (
    CandidateExecutionInput,
    CandidateIndexBuildSnapshot,
    capture_worker_runtime,
    normalize_evaluation_candidates,
)


def test_candidate_normalization_prepends_baseline_once_with_stable_order() -> None:
    first = uuid4()
    second = uuid4()

    assert normalize_evaluation_candidates(()) == (
        BM25_BASELINE_CONFIGURATION_VERSION_ID,
    )
    assert normalize_evaluation_candidates((first, second)) == (
        BM25_BASELINE_CONFIGURATION_VERSION_ID,
        first,
        second,
    )
    assert normalize_evaluation_candidates(
        (first, BM25_BASELINE_CONFIGURATION_VERSION_ID, second)
    ) == (BM25_BASELINE_CONFIGURATION_VERSION_ID, first, second)
    assert normalize_evaluation_candidates(
        (BM25_BASELINE_CONFIGURATION_VERSION_ID,)
    ) == (BM25_BASELINE_CONFIGURATION_VERSION_ID,)


def test_worker_runtime_requires_build_revision_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_WORKSHOP_BUILD_REVISION", raising=False)

    with pytest.raises(RuntimeError, match="revision"):
        capture_worker_runtime(environment="production")

    monkeypatch.setenv("AI_WORKSHOP_BUILD_REVISION", "release-abc123")
    runtime = capture_worker_runtime(environment="production")

    assert runtime["application_revision"] == "release-abc123"
    assert runtime["execution_role"] == "celery-worker"


def test_candidate_execution_input_requires_complete_concrete_build_manifest() -> None:
    profile_id = uuid4()
    build = CandidateIndexBuildSnapshot(
        asset_version_id=uuid4(),
        projection_id=uuid4(),
        index_build_id=uuid4(),
        index_name="rag-profile-build-a",
        indexing_profile_id=profile_id,
        vector_dimension=768,
        active_at_snapshot=True,
    )
    candidate = CandidateExecutionInput(
        id=uuid4(),
        configuration_id=uuid4(),
        configuration_version_id=uuid4(),
        ordinal=0,
        index_builds=(build,),
    )

    assert candidate.index_builds == (build,)
