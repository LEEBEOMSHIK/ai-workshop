"""Durable body-free Codex process capacity; unknown processes retain their slots."""

import sqlalchemy as sa

from alembic import op

revision = "0028_codex_execution_slots"
down_revision = "0027_codex_call_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rag_codex_execution_slots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("runner_ref", sa.String(120), nullable=False),
        sa.Column("configuration_sha256", sa.String(64), nullable=False),
        sa.Column("max_concurrent", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("configuration_sha256 ~ '^[0-9a-f]{64}$'", name="ck_codex_slot_digest"),
        sa.CheckConstraint("max_concurrent BETWEEN 1 AND 64", name="ck_codex_slot_capacity"),
        sa.CheckConstraint(
            "runner_ref ~ '^[a-z][a-z0-9]*-[a-z0-9]+(-[a-z0-9]+)*$'", name="ck_codex_slot_reference"
        ),
    )
    op.create_index(
        "ix_codex_execution_slots_runner_ref", "rag_codex_execution_slots", ["runner_ref"]
    )


def downgrade() -> None:
    connection = op.get_bind()
    # Serialize with writers and refuse to erase unresolved process evidence.
    connection.execute(sa.text("LOCK TABLE rag_codex_execution_slots IN ACCESS EXCLUSIVE MODE"))
    if connection.scalar(sa.text("SELECT EXISTS (SELECT 1 FROM rag_codex_execution_slots)")):
        raise RuntimeError("codex_slots_unresolved")
    op.drop_table("rag_codex_execution_slots")
