import hashlib
from pathlib import Path

from ai_workshop.labs.rag.evaluation.domain import load_evaluation_dataset

REPOSITORY_ROOT = Path(__file__).resolve().parents[6]
FIXTURE = REPOSITORY_ROOT / "sample-data/public/rag/evaluation/search-v1.json"


def test_public_fixture_is_frozen_hashed_and_covers_required_permission_cases() -> None:
    raw = FIXTURE.read_bytes()
    dataset = load_evaluation_dataset(raw)

    assert dataset.name == "자산운용 검색 평가"
    assert dataset.version == 1
    assert dataset.fixture_sha256 == hashlib.sha256(raw).hexdigest()
    assert len(dataset.document_snapshot_sha256) == 64
    assert len(dataset.query_set_sha256) == 64
    assert len(dataset.cases) >= 12
    assert [case.kind for case in dataset.cases] == [
        "exact_code",
        "korean_paraphrase",
        "numeric_clause",
        "table_cell",
        "insufficient_evidence",
        "conflicting_sources",
        "company_access",
        "personal_isolation",
        "temporary_expiry",
        "inactive_version",
        "semantic_highlight",
        "keyword_highlight",
    ]
    assert len({case.id for case in dataset.cases}) == len(dataset.cases)
    assert all(case.permission_scenario.name for case in dataset.cases)
    assert all(len(case.query_sha256) == 64 for case in dataset.cases)
    assert all(
        case.expected_evidence_ids
        or case.expected_answer_status.value == "insufficient_evidence"
        for case in dataset.cases
    )


def test_dataset_rejects_query_hash_tampering() -> None:
    raw = FIXTURE.read_bytes().replace(
        "위험등급 코드 A-17의 의미는?".encode(),
        "위험등급 코드 A-18의 의미는?".encode(),
        1,
    )

    try:
        load_evaluation_dataset(raw)
    except ValueError as exc:
        assert "query SHA-256" in str(exc)
    else:
        raise AssertionError("tampered query bytes must be rejected")
