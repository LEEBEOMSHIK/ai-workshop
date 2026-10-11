"""Immutable server-bound numeric proofs and schema3 candidate acceptance."""

from ai_workshop.labs.rag.generation.numeric_validation_sql import NUMERIC_PROOF_DDL
from alembic import op

revision = "0063_rag_numeric_proof"
down_revision = "0062_rag_access_epoch"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in NUMERIC_PROOF_DDL:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError("Immutable numeric proof rollback requires explicit review.")
