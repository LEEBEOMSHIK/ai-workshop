"""Subscribe the immutable system BM25 baseline to indexing demand."""

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa

from alembic import op

revision: str = "0013_system_baseline_indexing"
down_revision: str | Sequence[str] | None = "0012_terminal_rag_handoffs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BASELINE_VERSION_ID = UUID("00000000-0000-0000-0000-000000000503")
BASELINE_SUBSCRIPTION_ID = UUID("00000000-0000-0000-0000-000000000504")


def upgrade() -> None:
    op.create_table(
        "rag_system_indexing_subscriptions",
        sa.Column("configuration_version_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"],
            ["rag_configuration_versions.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("configuration_version_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO rag_system_indexing_subscriptions (
                configuration_version_id, id
            )
            SELECT version.id, :subscription_id
            FROM rag_configuration_versions AS version
            JOIN rag_configurations AS configuration
              ON configuration.id = version.configuration_id
            JOIN rag_profiles AS indexing
              ON indexing.id = version.indexing_profile_id
            JOIN rag_profiles AS retrieval
              ON retrieval.id = version.retrieval_profile_id
            WHERE version.id = :version_id
              AND configuration.is_system
              AND configuration.owner_id IS NULL
              AND indexing.kind = 'indexing'
              AND retrieval.kind = 'retrieval'
              AND retrieval.config::jsonb ->> 'indexing_profile_id'
                  = version.indexing_profile_id::text
              AND version.evaluation_state = 'pending'
              AND NOT version.is_default
            """
        ).bindparams(
            subscription_id=BASELINE_SUBSCRIPTION_ID,
            version_id=BASELINE_VERSION_ID,
        )
    )
    connection = op.get_bind()
    seeded = connection.scalar(
        sa.text(
            """
            SELECT count(*) FROM rag_system_indexing_subscriptions
            WHERE id = :subscription_id
              AND configuration_version_id = :version_id
            """
        ),
        {
            "subscription_id": BASELINE_SUBSCRIPTION_ID,
            "version_id": BASELINE_VERSION_ID,
        },
    )
    if seeded != 1:
        raise RuntimeError(
            "The exact compatible non-default BM25 baseline subscription is unavailable."
        )
    op.execute(
        """
        CREATE TRIGGER trg_rag_system_indexing_subscriptions_immutable
        BEFORE UPDATE OR DELETE ON rag_system_indexing_subscriptions
        FOR EACH ROW EXECUTE FUNCTION rag_reject_immutable_row_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_rag_system_indexing_subscriptions_immutable "
        "ON rag_system_indexing_subscriptions"
    )
    op.drop_table("rag_system_indexing_subscriptions")
