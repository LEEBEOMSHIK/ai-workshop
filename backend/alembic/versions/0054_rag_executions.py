"""Add bounded RAG execution observations without historical backfill."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0054_rag_executions"
down_revision = "0053_issue_numbers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_executions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "turn_id", sa.Uuid(), sa.ForeignKey("rag_conversation_turns.id", ondelete="RESTRICT")
        ),
        sa.Column("evaluation_attempt_id", sa.Uuid()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("answer_status", sa.String(40)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.Column("stages", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("turn_id", name="uq_rag_execution_turn"),
        sa.UniqueConstraint("evaluation_attempt_id", name="uq_rag_execution_attempt"),
        sa.CheckConstraint(
            "(turn_id IS NULL) <> (evaluation_attempt_id IS NULL)", name="ck_rag_execution_parent"
        ),
        sa.CheckConstraint(
            "status IN ('running','completed','failed','cancelled','interrupted')",
            name="ck_rag_execution_status",
        ),
    )
    op.create_index("ix_rag_executions_actor_created", "rag_executions", ["actor_id", "created_at"])
    op.add_column("rag_generation_execution_audits", sa.Column("execution_id", sa.Uuid()))
    op.create_foreign_key(
        "fk_rag_audit_execution",
        "rag_generation_execution_audits",
        "rag_executions",
        ["execution_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_rag_audit_execution", "rag_generation_execution_audits", ["execution_id"])
    # Existing turn finalization is the authoritative termination fence, including deletion.
    op.execute("""CREATE FUNCTION rag_sync_execution_turn() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NEW.status <> 'running' THEN
        UPDATE rag_executions SET status=NEW.status, error_code=NEW.error_code,
          answer_status=NEW.response->'generation'->>'status', ended_at=NEW.updated_at,
          updated_at=NEW.updated_at
        WHERE turn_id=NEW.id AND status='running';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER rag_sync_execution_turn AFTER UPDATE OF status
      ON rag_conversation_turns FOR EACH ROW EXECUTE FUNCTION rag_sync_execution_turn()""")


def downgrade() -> None:
    op.execute("DROP TRIGGER rag_sync_execution_turn ON rag_conversation_turns")
    op.execute("DROP FUNCTION rag_sync_execution_turn()")
    op.drop_index("ix_rag_audit_execution", table_name="rag_generation_execution_audits")
    op.drop_constraint(
        "fk_rag_audit_execution", "rag_generation_execution_audits", type_="foreignkey"
    )
    op.drop_column("rag_generation_execution_audits", "execution_id")
    op.drop_table("rag_executions")
