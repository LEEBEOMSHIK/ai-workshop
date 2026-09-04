from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.models.domain import (
    Profile,
    ProfileKind,
    ProfileValidationError,
)
from ai_workshop.labs.rag.models.schemas import parse_profile_yaml
from ai_workshop.shared.errors import AppError

PROFILE_ROOT = Path(__file__).resolve().parents[6] / "model-profiles" / "rag"


@pytest.mark.parametrize(
    ("relative_path", "expected_kind"),
    [
        ("indexing/baseline.yaml", ProfileKind.INDEXING),
        ("indexing/e5-structure-aware-v2.yaml", ProfileKind.INDEXING),
        ("indexing/bge-m3-structure-aware-v1.yaml", ProfileKind.INDEXING),
        ("retrieval/bm25.yaml", ProfileKind.RETRIEVAL),
        ("retrieval/hybrid-rrf.yaml", ProfileKind.RETRIEVAL),
        ("retrieval/hybrid-bge-m3-rrf-v1.yaml", ProfileKind.RETRIEVAL),
    ],
)
def test_default_yaml_profiles_are_valid_domain_profiles(
    relative_path: str, expected_kind: ProfileKind
) -> None:
    document = parse_profile_yaml(
        (PROFILE_ROOT / relative_path).read_text(encoding="utf-8"),
        expected_kind=expected_kind,
    )

    profile = Profile.create(
        kind=document.kind,
        name=document.name,
        version=document.version,
        config=document.config,
        bindings=tuple(item.to_domain() for item in document.bindings),
        evaluation_state=document.evaluation_state,
    )

    assert profile.kind is expected_kind
    assert profile.is_default is False


def test_legacy_generation_yaml_is_preserved_but_cannot_create_a_new_profile() -> None:
    document = parse_profile_yaml(
        (PROFILE_ROOT / "generation/local-baseline.yaml").read_text(encoding="utf-8"),
        expected_kind=ProfileKind.GENERATION,
    )

    with pytest.raises(ProfileValidationError, match="exactly one Deployment"):
        Profile.create(
            kind=document.kind,
            name=document.name,
            version=document.version,
            config=document.config,
            bindings=tuple(item.to_domain() for item in document.bindings),
            deployment_version_id=document.deployment_version_id,
            evaluation_state=document.evaluation_state,
        )


def test_e5_structure_aware_version_two_keeps_the_approved_chunking_values() -> None:
    document = parse_profile_yaml(
        (PROFILE_ROOT / "indexing/e5-structure-aware-v2.yaml").read_text(encoding="utf-8"),
        expected_kind=ProfileKind.INDEXING,
    )

    assert document.version == 2
    assert document.evaluation_state.value == "draft"
    assert document.config["chunker"] == {
        "name": "structure-aware",
        "version": 2,
        "target_tokens": 380,
        "overlap_tokens": 60,
    }
    assert document.bindings[0].role.value == "embedding"
    assert document.bindings[0].model_id == UUID("00000000-0000-0000-0000-000000000101")


def test_bge_profiles_are_dense_only_1024_dimension_technical_profiles() -> None:
    indexing = parse_profile_yaml(
        (PROFILE_ROOT / "indexing/bge-m3-structure-aware-v1.yaml").read_text("utf-8"),
        expected_kind=ProfileKind.INDEXING,
    )
    retrieval = parse_profile_yaml(
        (PROFILE_ROOT / "retrieval/hybrid-bge-m3-rrf-v1.yaml").read_text("utf-8"),
        expected_kind=ProfileKind.RETRIEVAL,
    )

    assert indexing.bindings[0].model_id == UUID(
        "00000000-0000-0000-0000-000000000102"
    )
    assert indexing.config["embedding"] == {"batch_size": 8, "similarity": "cosine"}
    assert retrieval.config["indexing_profile_id"] == (
        "00000000-0000-0000-0000-000000000204"
    )
    assert retrieval.config["reranker"] == {"enabled": False}


def test_legacy_hybrid_profile_preserves_its_optional_reranker_metadata() -> None:
    document = parse_profile_yaml(
        (PROFILE_ROOT / "retrieval/hybrid-rrf.yaml").read_text("utf-8"),
        expected_kind=ProfileKind.RETRIEVAL,
    )

    assert document.version == 1
    assert document.config["reranker"] == {"enabled": False, "optional": True}


def test_yaml_kind_must_match_the_registration_endpoint() -> None:
    content = """
kind: generation
name: generation-baseline
version: 1
config:
  prompt_ref: grounded-answer-v1
bindings: []
"""

    with pytest.raises(AppError) as exc_info:
        parse_profile_yaml(content, expected_kind=ProfileKind.RETRIEVAL)

    assert exc_info.value.code == "invalid_profile_yaml"
