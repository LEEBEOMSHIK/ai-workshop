"""Explicit workspace grants and atomic permission history."""

import sqlalchemy as sa

from alembic import op

revision = "0033_workspace_permissions"
down_revision = "0032_evidence_approval_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM workspace_memberships WHERE role NOT IN ('owner','member'))
          THEN RAISE EXCEPTION 'Unsupported workspace membership role'; END IF;
          IF EXISTS (
            SELECT 1 FROM workspaces w WHERE w.kind = 'personal' AND (
              NOT EXISTS (SELECT 1 FROM workspace_memberships m WHERE m.workspace_id = w.id
                          AND m.user_id = w.created_by AND m.role = 'owner')
              OR EXISTS (SELECT 1 FROM workspace_memberships m WHERE m.workspace_id = w.id
                         AND m.role = 'owner' AND m.user_id <> w.created_by)
            )
          ) THEN RAISE EXCEPTION 'Personal workspace owner membership mismatch'; END IF;
        END $$;
    """)
    op.add_column(
        "workspace_memberships",
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "workspace_memberships",
        sa.Column("can_write", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "workspace_memberships",
        sa.Column("can_delete", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "workspace_memberships",
        sa.Column("permission_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute("UPDATE workspace_memberships SET can_write = true, can_delete = (role = 'owner')")
    op.create_check_constraint(
        "ck_workspace_grants_read",
        "workspace_memberships",
        "can_read OR (NOT can_write AND NOT can_delete)",
    )
    op.create_check_constraint(
        "ck_workspace_permission_revision", "workspace_memberships", "permission_revision >= 1"
    )
    op.create_table(
        "workspace_permission_audits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.Uuid(),
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "target_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("before_permissions", sa.JSON()),
        sa.Column("after_permissions", sa.JSON(), nullable=False),
        sa.Column("permission_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("""
        CREATE FUNCTION guard_workspace_permission_audit() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Workspace permission history is immutable'; END $$;
        CREATE TRIGGER workspace_permission_audit_guard BEFORE UPDATE OR DELETE
        ON workspace_permission_audits FOR EACH ROW
        EXECUTE FUNCTION guard_workspace_permission_audit();
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM workspace_permission_audits) THEN
            RAISE EXCEPTION 'Cannot discard workspace permission history';
          END IF;
        END $$;
    """)
    op.drop_table("workspace_permission_audits")
    op.execute("DROP FUNCTION guard_workspace_permission_audit()")
    op.drop_constraint("ck_workspace_grants_read", "workspace_memberships")
    op.drop_constraint("ck_workspace_permission_revision", "workspace_memberships")
    for name in ("permission_revision", "can_delete", "can_write", "can_read"):
        op.drop_column("workspace_memberships", name)
