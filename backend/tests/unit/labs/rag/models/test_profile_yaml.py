from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.models.domain import Profile, ProfileKind
from ai_workshop.labs.rag.models.schemas import parse_profile_yaml
from ai_workshop.shared.errors import AppError

PROFILE_ROOT = Path(__file__).resolve().parents[6] / "model-profiles" / "rag"


@pytest.mark.parametrize(
    ("relative_path", "expected_kind"),
    [
        ("indexing/baseline.yaml", ProfileKind.INDEXING),
        ("indexing/e5-structure-aware-v2.yaml", ProfileKind.INDEXING),
        ("retrieval/bm25.yaml", ProfileKind.RETRIEVAL),
        ("retrieval/hybrid-rrf.yaml", ProfileKind.RETRIEVAL),
        ("generation/local-baseline.yaml", ProfileKind.GENERATION),
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
