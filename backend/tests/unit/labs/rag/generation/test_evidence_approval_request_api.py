from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ai_workshop.config import Settings
from ai_workshop.labs.rag.generation.evidence_approval_request_schemas import (
    EvidenceApprovalRequestCreate,
    EvidenceApprovalRequestDecision,
)
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole


def test_request_routes_require_authentication_before_accessing_documents() -> None:
    client = TestClient(create_app())
    for path in (
        "/api/v1/rag/evidence-approval-requests",
        "/api/v1/admin/rag/evidence-approval-requests",
    ):
        assert client.get(path).status_code == 401
    assert (
        client.post(
            "/api/v1/admin/rag/evidence-approval-requests/" + str(uuid4()) + "/decision",
            json={},
        ).status_code
        == 401
    )


def test_self_schema_has_no_actor_hash_or_free_text_fields() -> None:
    schemas = create_app().openapi()["components"]["schemas"]
    assert "EvidenceApprovalRequestCreate" in schemas
    assert set(schemas["EvidenceApprovalRequestCreate"]["properties"]) == {
        "request_id",
        "revision_id",
        "provider",
        "expected_approval_generation",
    }
    assert set(schemas["EvidenceApprovalRequestResponse"]["properties"]) == {
        "id",
        "revision_id",
        "provider",
        "status",
        "state_revision",
        "created_at",
        "resolved_at",
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"prompt": "secret"},
        {"actor_id": str(uuid4())},
        {"content_sha256": "a" * 64},
        {"provider": "openai"},
        {"expected_approval_generation": True},
        {"expected_approval_generation": -1},
    ],
)
def test_request_rejects_injected_identity_content_provider_or_invalid_cas(extra) -> None:
    with pytest.raises(ValidationError):
        EvidenceApprovalRequestCreate.model_validate(
            {
                "request_id": uuid4(),
                "revision_id": uuid4(),
                "provider": "development_codex_exec",
                "expected_approval_generation": 0,
                **extra,
            }
        )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"classification": "synthetic"},
        {"content_sha256": "a" * 64},
        {"classification": "private", "content_sha256": "a" * 64},
        {"classification": "synthetic", "content_sha256": "bad"},
    ],
)
def test_approve_requires_explicit_classification_and_exact_hash(fields) -> None:
    with pytest.raises(ValidationError):
        EvidenceApprovalRequestDecision.model_validate(
            {
                "request_id": uuid4(),
                "expected_state_revision": 0,
                "expected_approval_generation": 0,
                "decision": "approve",
                **fields,
            }
        )


def test_member_cannot_list_or_decide_admin_requests() -> None:
    app = create_app()
    user = User(uuid4(), "Member", "m@example.test", "m@example.test", "fixture", UserRole.MEMBER)
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app)
    assert client.get("/api/v1/admin/rag/evidence-approval-requests").status_code == 403
    assert (
        client.post(
            f"/api/v1/admin/rag/evidence-approval-requests/{uuid4()}/decision",
            json={},
        ).status_code
        == 403
    )


def test_cursor_is_signed_and_scoped_to_actor_view_and_revision() -> None:
    from datetime import UTC, datetime

    from ai_workshop.labs.rag.generation.evidence_approval_request_cursor import RequestCursor
    from ai_workshop.shared.errors import AppError

    codec = RequestCursor(Settings(secret_key="request-tests-secret-32-characters"))
    scope = [str(uuid4()), "self", str(uuid4()), "development_codex_exec"]
    time, id = datetime.now(UTC), uuid4()
    token = codec.encode(scope, time, id)
    assert codec.decode(token, scope) == (time, id)
    for index in range(4):
        wrong = list(scope)
        wrong[index] = "other"
        with pytest.raises(AppError):
            codec.decode(token, wrong)
    for invalid in ("!", token[:-2] + "xx", "x" * 4097):
        with pytest.raises(AppError):
            codec.decode(invalid, scope)


def test_alembic_registers_request_tables_in_a_fresh_process() -> None:
    """App imports must not mask missing metadata in the migration entry point."""
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[5]
    script = """
import json
from alembic.config import Config
from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory

config = Config('alembic.ini')
scripts = ScriptDirectory.from_config(config)
with EnvironmentContext(config, scripts, as_sql=True, fn=lambda revisions, context: []):
    scripts.run_env()
from ai_workshop.shared.models import Base
print(json.dumps(sorted(Base.metadata.tables)))
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=backend_root,
        env={**os.environ, "AI_WORKSHOP_SECRET_KEY": "offline-metadata-test-secret-value"},
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    tables = json.loads(result.stdout.strip().splitlines()[-1])
    assert "rag_evidence_approval_requests" in tables
    assert "rag_evidence_approval_request_receipts" in tables
