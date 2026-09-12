"""Create dynamic RAG domains and immutable connection versions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023_rag_domains"
down_revision: str | Sequence[str] | None = "0022_mixed_pdf_ocr_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[object], sa.Column[object]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "rag_domains",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(180), nullable=False),
        sa.Column("description", sa.String(1000), nullable=False),
        sa.Column("active_connection_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "slug ~ '^[a-z0-9]+(-[a-z0-9]+)*$'",
            name="ck_rag_domains_slug",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_rag_domains_slug"),
    )
    op.create_table(
        "rag_domain_connection_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("domain_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("configuration_version_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("version > 0", name="ck_rag_domain_connections_positive"),
        sa.ForeignKeyConstraint(
            ["domain_id"], ["rag_domains.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["configuration_version_id"],
            ["rag_configuration_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "domain_id",
            "version",
            name="uq_rag_domain_connection_versions_domain_version",
        ),
        sa.UniqueConstraint(
            "id",
            "domain_id",
            name="uq_rag_domain_connection_versions_id_domain",
        ),
        sa.UniqueConstraint(
            "id",
            "configuration_version_id",
            name="uq_rag_domain_connection_versions_id_configuration",
        ),
    )
    op.create_foreign_key(
        "fk_rag_domains_active_connection",
        "rag_domains",
        "rag_domain_connection_versions",
        ["active_connection_version_id", "id"],
        ["id", "domain_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "rag_domain_connection_scope_seals",
        sa.Column("connection_version_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_version_id"],
            ["rag_domain_connection_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("connection_version_id"),
    )
    op.create_table(
        "rag_domain_connection_workspaces",
        sa.Column("connection_version_id", sa.Uuid(), nullable=False),
        sa.Column("configuration_version_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["connection_version_id", "configuration_version_id"],
            [
                "rag_domain_connection_versions.id",
                "rag_domain_connection_versions.configuration_version_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["configuration_version_id", "workspace_id"],
            [
                "rag_configuration_workspace_subscriptions.configuration_version_id",
                "rag_configuration_workspace_subscriptions.workspace_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("connection_version_id", "workspace_id"),
    )
    op.execute(
        """
        CREATE FUNCTION rag_reject_domain_slug_update_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.slug IS DISTINCT FROM OLD.slug THEN
                RAISE EXCEPTION 'RAG domain slug is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_domains_slug_immutable
        BEFORE UPDATE ON rag_domains
        FOR EACH ROW EXECUTE FUNCTION rag_reject_domain_slug_update_v1()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_reject_domain_connection_mutation_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'RAG domain connection versions are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_seal_domain_connection_scope_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO rag_domain_connection_scope_seals (connection_version_id)
            VALUES (NEW.id);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_rag_domain_connection_versions_seal_scope
        AFTER INSERT ON rag_domain_connection_versions
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION rag_seal_domain_connection_scope_v1()
        """
    )
    op.execute(
        """
        CREATE FUNCTION rag_restrict_domain_connection_workspace_insert_v1()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
            parent_exists boolean;
        BEGIN
            SELECT true INTO parent_exists
            FROM rag_domain_connection_versions
            WHERE id = NEW.connection_version_id;

            IF parent_exists IS DISTINCT FROM true THEN
                RAISE EXCEPTION
                    'RAG domain connection scope must be created atomically';
            END IF;
            IF EXISTS (
                SELECT 1
                FROM rag_domain_connection_scope_seals
                WHERE connection_version_id = NEW.connection_version_id
            ) THEN
                RAISE EXCEPTION 'RAG domain connection scope is immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_rag_domain_connection_workspaces_insert_unsealed
        BEFORE INSERT ON rag_domain_connection_workspaces
        FOR EACH ROW
        EXECUTE FUNCTION rag_restrict_domain_connection_workspace_insert_v1()
        """
    )
    for table_name in (
        "rag_domain_connection_versions",
        "rag_domain_connection_scope_seals",
        "rag_domain_connection_workspaces",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION rag_reject_domain_connection_mutation_v1()
            """
        )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER trg_rag_domain_connection_workspaces_insert_unsealed "
        "ON rag_domain_connection_workspaces"
    )
    op.execute("DROP FUNCTION rag_restrict_domain_connection_workspace_insert_v1()")
    op.execute(
        "DROP TRIGGER trg_rag_domain_connection_versions_seal_scope "
        "ON rag_domain_connection_versions"
    )
    op.execute("DROP FUNCTION rag_seal_domain_connection_scope_v1()")
    for table_name in (
        "rag_domain_connection_workspaces",
        "rag_domain_connection_scope_seals",
        "rag_domain_connection_versions",
    ):
        op.execute(f"DROP TRIGGER trg_{table_name}_immutable ON {table_name}")
    op.execute("DROP FUNCTION rag_reject_domain_connection_mutation_v1()")
    op.execute("DROP TRIGGER trg_rag_domains_slug_immutable ON rag_domains")
    op.execute("DROP FUNCTION rag_reject_domain_slug_update_v1()")
    op.drop_table("rag_domain_connection_workspaces")
    op.drop_table("rag_domain_connection_scope_seals")
    op.drop_constraint(
        "fk_rag_domains_active_connection",
        "rag_domains",
        type_="foreignkey",
    )
    op.drop_table("rag_domain_connection_versions")
    op.drop_table("rag_domains")
