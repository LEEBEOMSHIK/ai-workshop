"""Nullable verification bindings must satisfy the PostgreSQL object constraint."""

import json

from sqlalchemy import create_engine

from ai_workshop.labs.rag.generation.codex_verification_models import (
    CodexVerificationAttemptRecord,
)

# Creating the dialect does not connect to PostgreSQL.
POSTGRESQL_DIALECT = create_engine("postgresql+psycopg://").dialect


def test_failed_verification_binding_is_bound_as_sql_null() -> None:
    binding_type = CodexVerificationAttemptRecord.__table__.c.binding.type
    processor = binding_type.bind_processor(POSTGRESQL_DIALECT)

    assert processor is not None
    assert processor(None) is None


def test_successful_verification_binding_remains_a_json_object() -> None:
    binding_type = CodexVerificationAttemptRecord.__table__.c.binding.type
    processor = binding_type.bind_processor(POSTGRESQL_DIALECT)
    binding = {"provider_model_id": "synthetic-model", "context_prompt": {"version": 1}}

    assert processor is not None
    assert json.loads(processor(binding)) == binding
