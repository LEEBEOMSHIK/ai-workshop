import pytest

from tests.integration.labs.rag.search.test_search_api import (
    verify_postgresql_current_approval_policy_strengthening_and_audit_hygiene,
)


def test_openai_policy_flow_fails_closed_and_keeps_audits_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the end-to-end PostgreSQL policy lock, runtime, and audit contract."""
    verify_postgresql_current_approval_policy_strengthening_and_audit_hygiene(
        monkeypatch
    )
