import json
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
)
from ai_workshop.labs.rag.evaluation import service as evaluation_service
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
    assert len(cast(str, runtime["application_source_sha256"])) == 64
    assert set(
        cast(dict[str, str], runtime["packages"])
    ).issuperset({"numpy", "tokenizers", "torch", "transformers"})
    assert "cuda_runtime" in cast(dict[str, object], runtime["model_runtime"])


def test_development_worker_revision_is_bound_to_the_source_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AI_WORKSHOP_BUILD_REVISION", raising=False)

    runtime = capture_worker_runtime(environment="test")

    source_sha256 = cast(str, runtime["application_source_sha256"])
    assert runtime["application_revision"] == f"source-sha256:{source_sha256}"


def test_cuda_worker_fingerprint_is_json_native_for_exact_resume_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_cuda = SimpleNamespace(
        is_available=lambda: True,
        device_count=lambda: 1,
        current_device=lambda: 0,
        get_device_name=lambda _index: "synthetic-cuda-device",
        get_device_capability=lambda _index: (8, 9),
    )
    fake_torch = SimpleNamespace(
        __version__="2.test",
        cuda=fake_cuda,
        version=SimpleNamespace(cuda="12.test"),
        backends=SimpleNamespace(cudnn=SimpleNamespace(version=lambda: 9010)),
    )
    monkeypatch.setattr(
        evaluation_service,
        "import_module",
        lambda _package: fake_torch,
    )

    runtime = capture_worker_runtime(environment="test")

    assert json.loads(json.dumps(runtime)) == runtime
    model_runtime = cast(dict[str, object], runtime["model_runtime"])
    assert model_runtime["active_cuda_device_capability"] == [8, 9]


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
