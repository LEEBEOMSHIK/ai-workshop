"""Allocate category-independent issue numbers and retain previous identifiers."""

from datetime import UTC, datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "0053_issue_numbers"
down_revision = "0052_issue_category_hierarchy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "SELECT pg_advisory_xact_lock(hashtextextended('issue-history-category-hierarchy', 0))"
        )
    )
    op.add_column(
        "issues",
        sa.Column("legacy_keys", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.create_check_constraint(
        "ck_issues_legacy_keys_array", "issues", "jsonb_typeof(legacy_keys) = 'array'"
    )
    op.create_table(
        "issue_identifiers",
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("issue_id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_issue_identifiers"),
        sa.ForeignKeyConstraint(
            ["issue_id"], ["issues.id"], name="fk_issue_identifiers_issue", ondelete="RESTRICT"
        ),
    )
    op.create_index("ix_issue_identifiers_issue_id", "issue_identifiers", ["issue_id"])
    op.create_table(
        "issue_number_sequences",
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("next_value", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("scope", name="pk_issue_number_sequences"),
        sa.CheckConstraint("scope = 'global'", name="ck_issue_number_sequences_scope"),
        sa.CheckConstraint("next_value > 0", name="ck_issue_number_sequences_positive"),
    )
    rows = (
        connection.execute(
            sa.text('SELECT id,issue_key,revision FROM issues ORDER BY issue_key COLLATE "C",id')
        )
        .mappings()
        .all()
    )
    reserved = {row["issue_key"] for row in rows}
    # Free the canonical unique namespace before assigning sorted neutral keys.
    for row in rows:
        connection.execute(
            sa.text(
                "UPDATE issues SET issue_key=:temporary,"
                "legacy_keys=jsonb_build_array(CAST(:old_key AS text)) WHERE id=:id"
            ),
            {"id": row["id"], "old_key": row["issue_key"], "temporary": f"migration-{uuid4()}"},
        )
    number = 1
    now = datetime.now(UTC)
    events = sa.table(
        "issue_events",
        sa.column("id", sa.Uuid()),
        sa.column("issue_id", sa.Uuid()),
        sa.column("event_date", sa.Date()),
        sa.column("recorded_at", sa.DateTime(timezone=True)),
        sa.column("actor_id", sa.Uuid()),
        sa.column("kind", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("before_revision", sa.Integer()),
        sa.column("after_revision", sa.Integer()),
        sa.column("snapshot", JSONB()),
    )
    for row in rows:
        while f"ISSUE-{number:05d}" in reserved:
            number += 1
        key = f"ISSUE-{number:05d}"
        number += 1
        connection.execute(
            sa.text(
                "UPDATE issues SET issue_key=:key,revision=revision+1,updated_at=:now WHERE id=:id"
            ),
            {"id": row["id"], "key": key, "now": now},
        )
        connection.execute(
            events.insert().values(
                id=uuid4(),
                issue_id=row["id"],
                event_date=now.date(),
                recorded_at=now,
                actor_id=None,
                kind="key_renumbered",
                description="문제 번호를 기술 분류와 독립된 번호로 전환했습니다.",
                before_revision=row["revision"],
                after_revision=row["revision"] + 1,
                snapshot={
                    "before": {"issue_key": row["issue_key"], "revision": row["revision"]},
                    "after": {
                        "issue_key": key,
                        "legacy_keys": [row["issue_key"]],
                        "revision": row["revision"] + 1,
                    },
                    "source": "migration-0053",
                },
            )
        )
    connection.execute(
        sa.text("INSERT INTO issue_number_sequences(scope,next_value) VALUES ('global',:number)"),
        {"number": number},
    )
    connection.execute(
        sa.text(
            "INSERT INTO issue_identifiers(key,issue_id) SELECT issue_key,id FROM issues "
            "UNION SELECT jsonb_array_elements_text(legacy_keys),id FROM issues"
        )
    )
    op.create_check_constraint("ck_issues_neutral_key", "issues", "issue_key ~ '^ISSUE-[0-9]{5,}$'")
    op.execute("""CREATE FUNCTION issue_history_sync_identifiers() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
      DELETE FROM issue_identifiers WHERE issue_id=NEW.id;
      INSERT INTO issue_identifiers(key,issue_id)
      SELECT NEW.issue_key,NEW.id
      UNION SELECT jsonb_array_elements_text(NEW.legacy_keys),NEW.id;
      RETURN NEW;
    END $$""")
    op.execute("""CREATE TRIGGER issues_identifiers_sync
    AFTER INSERT OR UPDATE OF issue_key,legacy_keys ON issues
    FOR EACH ROW EXECUTE FUNCTION issue_history_sync_identifiers()""")


def downgrade() -> None:
    raise RuntimeError(
        "Issue number migration preserves permanent identifier aliases. "
        "Roll back the application while retaining this additive schema."
    )
