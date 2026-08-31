"""Subscribe the immutable system BM25 baseline to indexing demand."""

import json
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
BASELINE_CONFIGURATION_ID = UUID("00000000-0000-0000-0000-000000000501")
BASELINE_POLICY_ID = UUID("00000000-0000-0000-0000-000000000502")
E5_MODEL_ID = UUID("00000000-0000-0000-0000-000000000101")
E5_INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000201")
BM25_RETRIEVAL_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000202")
E5_PROFILE_BINDING_ID = UUID("00000000-0000-0000-0000-000000000203")

E5_MODEL_CONFIG = {
    "repo_id": "intfloat/multilingual-e5-base",
    "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
    "dimension": 768,
    "max_tokens": 512,
    "query_prefix": "query: ",
    "document_prefix": "passage: ",
    "normalize": True,
    "device": "cpu",
    "dtype": "float32",
    "output_mode": "dense",
    "data_policy": "local_only",
}
E5_INDEXING_CONFIG = {
    "chunker": {
        "name": "structure-aware",
        "version": 2,
        "target_tokens": 380,
        "overlap_tokens": 60,
    },
    "embedding": {"batch_size": 32, "similarity": "cosine"},
}
BM25_RETRIEVAL_CONFIG = {
    "bm25": {"analyzer": "standard", "top_k": 30},
    "indexing_profile_id": str(E5_INDEXING_PROFILE_ID),
}


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
    _restore_fully_missing_approved_baseline()
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


def _restore_fully_missing_approved_baseline() -> None:
    """Restore only an entirely absent 0009 seed; partial state remains fatal."""
    connection = op.get_bind()
    exact_seed_rows = connection.scalar(
        sa.text(
            """
            SELECT
                (SELECT count(*) FROM rag_model_definitions
                 WHERE id = :model_id OR (
                    kind = 'embedding' AND name = 'multilingual-e5-base'
                    AND version = 1
                 ))
              + (SELECT count(*) FROM rag_profiles
                 WHERE id IN (:indexing_profile_id, :retrieval_profile_id) OR (
                    kind = 'indexing' AND name = 'e5-structure-aware'
                    AND version = 2
                 ) OR (
                    kind = 'retrieval' AND name = 'bm25-baseline'
                    AND version = 1
                 ))
              + (SELECT count(*) FROM rag_profile_model_bindings
                 WHERE id = :binding_id)
              + (SELECT count(*) FROM rag_configurations
                 WHERE id = :configuration_id OR name = 'BM25 기준선')
              + (SELECT count(*) FROM rag_answer_policy_versions
                 WHERE id = :policy_id)
              + (SELECT count(*) FROM rag_configuration_versions
                 WHERE id = :version_id)
            """
        ),
        {
            "model_id": E5_MODEL_ID,
            "indexing_profile_id": E5_INDEXING_PROFILE_ID,
            "retrieval_profile_id": BM25_RETRIEVAL_PROFILE_ID,
            "binding_id": E5_PROFILE_BINDING_ID,
            "configuration_id": BASELINE_CONFIGURATION_ID,
            "policy_id": BASELINE_POLICY_ID,
            "version_id": BASELINE_VERSION_ID,
        },
    )
    if exact_seed_rows:
        baseline_exists = connection.scalar(
            sa.text(
                "SELECT count(*) FROM rag_configuration_versions WHERE id = :id"
            ),
            {"id": BASELINE_VERSION_ID},
        )
        if baseline_exists == 1:
            return
        raise RuntimeError(
            "The approved BM25 baseline seed is partially present or conflicting."
        )

    connection.execute(
        sa.text(
            """
            INSERT INTO rag_model_definitions (kind, name, version, config, id)
            VALUES ('embedding', 'multilingual-e5-base', 1, CAST(:config AS json), :id)
            """
        ),
        {"config": json.dumps(E5_MODEL_CONFIG), "id": E5_MODEL_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profiles (
                kind, name, version, config, evaluation_state, is_default, id
            ) VALUES (
                'indexing', 'e5-structure-aware', 2, CAST(:config AS json),
                'draft', false, :id
            )
            """
        ),
        {"config": json.dumps(E5_INDEXING_CONFIG), "id": E5_INDEXING_PROFILE_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profile_model_bindings (profile_id, role, model_id, id)
            VALUES (:profile_id, 'embedding', :model_id, :id)
            """
        ),
        {
            "profile_id": E5_INDEXING_PROFILE_ID,
            "model_id": E5_MODEL_ID,
            "id": E5_PROFILE_BINDING_ID,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_profiles (
                kind, name, version, config, evaluation_state, is_default, id
            ) VALUES (
                'retrieval', 'bm25-baseline', 1, CAST(:config AS json),
                'draft', false, :id
            )
            """
        ),
        {
            "config": json.dumps(BM25_RETRIEVAL_CONFIG),
            "id": BM25_RETRIEVAL_PROFILE_ID,
        },
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_configurations (owner_id, name, is_system, id)
            VALUES (NULL, 'BM25 기준선', true, :id)
            """
        ),
        {"id": BASELINE_CONFIGURATION_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_answer_policy_versions (
                configuration_id, version, mode, min_semantic_score,
                min_keyword_coverage, require_complete_provenance,
                conflict_mode, id
            ) VALUES (
                :configuration_id, 1, 'extractive', 0.8, 0.7, true,
                'separate_sources', :id
            )
            """
        ),
        {"configuration_id": BASELINE_CONFIGURATION_ID, "id": BASELINE_POLICY_ID},
    )
    connection.execute(
        sa.text(
            """
            INSERT INTO rag_configuration_versions (
                configuration_id, version, indexing_profile_id,
                retrieval_profile_id, generation_profile_id,
                answer_policy_version_id, evaluation_state, is_default, id
            ) VALUES (
                :configuration_id, 1, :indexing_profile_id,
                :retrieval_profile_id, NULL, :policy_id, 'pending', false, :id
            )
            """
        ),
        {
            "configuration_id": BASELINE_CONFIGURATION_ID,
            "indexing_profile_id": E5_INDEXING_PROFILE_ID,
            "retrieval_profile_id": BM25_RETRIEVAL_PROFILE_ID,
            "policy_id": BASELINE_POLICY_ID,
            "id": BASELINE_VERSION_ID,
        },
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_rag_system_indexing_subscriptions_immutable "
        "ON rag_system_indexing_subscriptions"
    )
    op.drop_table("rag_system_indexing_subscriptions")
