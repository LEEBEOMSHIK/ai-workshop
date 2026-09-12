"""Add master-protected technology authorization state and audit."""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0030_technology_permissions"
down_revision: str | Sequence[str] | None = "0029_codex_verification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    user_count = int(connection.scalar(sa.text("SELECT COUNT(*) FROM users")) or 0)
    invalid_roles = int(
        connection.scalar(
            sa.text("SELECT COUNT(*) FROM users WHERE role NOT IN ('owner', 'member')")
        )
        or 0
    )
    if invalid_roles:
        raise RuntimeError("invalid_user_role_state")
    active_owner_count = int(
        connection.scalar(sa.text("SELECT COUNT(*) FROM users WHERE role = 'owner' AND is_active"))
        or 0
    )
    if user_count and not active_owner_count:
        raise RuntimeError("active_owner_required")

    op.create_check_constraint(
        "ck_users_authorization_role",
        "users",
        "role IN ('owner', 'member')",
    )
    op.create_table(
        "authorization_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("initialized", sa.Boolean(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_authorization_state_singleton"),
        sa.PrimaryKeyConstraint("id", name="pk_authorization_state"),
    )
    op.create_table(
        "user_authorization_states",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", name="fk_user_authorization_user", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("revision", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "revision >= 0",
            name="ck_user_authorization_revision_nonnegative",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_user_authorization_states"),
        sa.UniqueConstraint("user_id", name="uq_user_authorization_user"),
    )
    op.create_table(
        "technology_grants",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", name="fk_technology_grant_user", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("technology_key", sa.String(80), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False),
        sa.Column("can_configure", sa.Boolean(), nullable=False),
        sa.Column("can_execute", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "can_view OR (NOT can_configure AND NOT can_execute)",
            name="ck_technology_grant_view_prerequisite",
        ),
        sa.CheckConstraint("can_view", name="ck_technology_grant_nonempty"),
        sa.PrimaryKeyConstraint("user_id", "technology_key", name="pk_technology_grants"),
        sa.UniqueConstraint(
            "user_id",
            "technology_key",
            name="uq_technology_grant_user_key",
        ),
    )
    op.create_table(
        "authority_audit",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column(
            "actor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", name="fk_authority_audit_actor", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "target_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", name="fk_authority_audit_target", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("technology_key", sa.String(80), nullable=True),
        sa.Column("before", JSONB(), nullable=False),
        sa.Column("after", JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("jsonb_typeof(before) = 'object'", name="ck_authority_audit_before"),
        sa.CheckConstraint("jsonb_typeof(after) = 'object'", name="ck_authority_audit_after"),
        sa.PrimaryKeyConstraint("id", name="pk_authority_audit"),
    )
    op.create_index(
        "ix_authority_audit_target_id_desc",
        "authority_audit",
        ["target_user_id", sa.text("id DESC")],
    )
    connection.execute(
        sa.text("INSERT INTO authorization_state (id, initialized) VALUES (1, :initialized)"),
        {"initialized": bool(user_count)},
    )
    if user_count:
        connection.execute(
            sa.text(
                "INSERT INTO user_authorization_states (user_id, revision) SELECT id, 0 FROM users"
            )
        )
    op.execute(
        """CREATE FUNCTION authority_audit_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'authority_audit_append_only'; END; $$"""
    )
    op.execute(
        """CREATE TRIGGER authority_audit_append_only
        BEFORE UPDATE OR DELETE ON authority_audit
        FOR EACH ROW EXECUTE FUNCTION authority_audit_append_only()"""
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "LOCK TABLE authorization_state, user_authorization_states, "
            "technology_grants, authority_audit IN ACCESS EXCLUSIVE MODE"
        )
    )
    changed = connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM technology_grants) "
            "OR EXISTS (SELECT 1 FROM authority_audit) "
            "OR EXISTS (SELECT 1 FROM user_authorization_states WHERE revision <> 0)"
        )
    )
    if changed:
        raise RuntimeError("technology_authorization_records_exist")
    op.drop_index("ix_authority_audit_target_id_desc", table_name="authority_audit")
    op.drop_table("authority_audit")
    op.execute("DROP FUNCTION authority_audit_append_only()")
    op.drop_table("technology_grants")
    op.drop_table("user_authorization_states")
    op.drop_table("authorization_state")
    op.drop_constraint("ck_users_authorization_role", "users", type_="check")
