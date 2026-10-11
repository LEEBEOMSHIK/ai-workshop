from pathlib import Path
from runpy import run_path


def test_numeric_migration_preserves_legacy_gate_oid_and_has_exact_parent():
    migration = run_path(str(Path("alembic/versions/0063_rag_numeric_proof.py")))
    assert migration["revision"] == "0063_rag_numeric_proof"
    assert migration["down_revision"] == "0062_rag_access_epoch"
    from ai_workshop.labs.rag.generation.numeric_validation_sql import NUMERIC_PROOF_DDL

    sql = "\n".join(NUMERIC_PROOF_DDL)
    assert "pg_get_functiondef" in sql and "anchor_count" in sql
    assert "ALTER FUNCTION" not in sql and "RENAME" not in sql
    assert "BEFORE UPDATE OR DELETE" in sql


def test_numeric_sql_binds_payload_to_authoritative_execution_and_registered_policy():
    from ai_workshop.labs.rag.generation.numeric_validation_sql import NUMERIC_PROOF_DDL
    from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1

    sql = "\n".join(NUMERIC_PROOF_DDL)
    assert SOURCE_NUMERIC_PROOF_V1.digest in sql
    for contract in (
        "a.execution_id",
        "r.owner_id",
        "v.generation_profile_id",
        "rag_generative_canonical(payload)",
        "operand->>'evidence_id'",
        "operand->>'char_start'",
        "audit.policy_allowed",
        "profile->'config'",
    ):
        assert contract in sql
    assert sql.index("IF schema_version IN (1,2) THEN RETURN") < sql.index(
        "SELECT * INTO STRICT receipt"
    )


def test_existing_audit_orm_has_no_numeric_columns_for_schema0061():
    from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord

    assert not any(
        "numeric" in column.name or "catalogue" in column.name
        for column in GenerationExecutionAuditRecord.__table__.columns
    )


def test_numeric_gate_keeps_ready_historical_inputs_independent_of_activation():
    from ai_workshop.labs.rag.generation.numeric_validation_sql import NUMERIC_PROOF_DDL

    assert "ib.is_active" not in "\n".join(NUMERIC_PROOF_DDL)
