"""Keep only the current private learning draft for each record."""

from alembic import op

revision = "0069_learning_current_only"
down_revision = "0068_anthropic_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Writers update the parent by compare-and-swap, then insert its new draft.
    # Lock in the same order to isolate the initial purge from concurrent edits.
    op.execute(
        "LOCK TABLE learning_records, learning_record_revisions IN SHARE ROW EXCLUSIVE MODE"
    )
    op.execute(
        """DELETE FROM learning_record_revisions AS d USING learning_records AS r
           WHERE d.record_id = r.id AND d.revision <> r.current_revision"""
    )
    op.create_unique_constraint(
        "uq_learning_current_draft", "learning_record_revisions", ["record_id"]
    )
    op.execute(
        """CREATE FUNCTION replace_learning_draft() RETURNS trigger LANGUAGE plpgsql AS $$
           BEGIN
             DELETE FROM learning_record_revisions AS d USING learning_records AS r
              WHERE d.record_id = NEW.record_id AND r.id = NEW.record_id
                AND r.current_revision = NEW.revision AND d.revision <> NEW.revision;
             RETURN NEW;
           END
           $$"""
    )
    op.execute(
        """CREATE TRIGGER replace_learning_draft BEFORE INSERT ON learning_record_revisions
           FOR EACH ROW EXECUTE FUNCTION replace_learning_draft()"""
    )


def downgrade() -> None:
    # Restores the old write policy. Deleted historical bodies cannot be recovered.
    op.execute("DROP TRIGGER replace_learning_draft ON learning_record_revisions")
    op.execute("DROP FUNCTION replace_learning_draft()")
    op.drop_constraint("uq_learning_current_draft", "learning_record_revisions", type_="unique")
