"""Add two-level issue categories while preserving assigned category identities."""

from uuid import uuid4

import sqlalchemy as sa

from alembic import op

revision = "0052_issue_category_hierarchy"
down_revision = "0051_issue_history"
branch_labels = None
depends_on = None

RAG_CODES = (
    "conversation-lifecycle",
    "attachments",
    "conversation-ui",
    "document-selection",
    "retrieval-evidence",
    "conversation-readiness",
)
PLATFORM_CODES = ("request-transport", "local-environment")


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "SELECT pg_advisory_xact_lock(hashtextextended('issue-history-category-hierarchy', 0))"
        )
    )
    unknown = connection.execute(
        sa.text(
            "SELECT DISTINCT c.code FROM issue_categories c "
            "JOIN issues i ON i.category_id=c.id WHERE c.code NOT IN :codes"
        ).bindparams(sa.bindparam("codes", expanding=True)),
        {"codes": RAG_CODES + PLATFORM_CODES},
    ).first()
    if unknown is not None:
        raise RuntimeError(
            "Issue category migration requires explicit classification for assigned categories."
        )
    if connection.execute(
        sa.text("SELECT 1 FROM issue_categories WHERE code IN ('rag','platform')")
    ).first():
        raise RuntimeError(
            "Reserved issue root category codes already exist; resolve before migration."
        )
    op.add_column("issue_categories", sa.Column("parent_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_issue_categories_parent",
        "issue_categories",
        "issue_categories",
        ["parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_issue_categories_not_self", "issue_categories", "parent_id IS NULL OR parent_id <> id"
    )
    op.create_index("ix_issue_categories_parent_id", "issue_categories", ["parent_id"])
    for order, (code, name, children) in enumerate(
        (("rag", "RAG", RAG_CODES), ("platform", "공통 플랫폼", PLATFORM_CODES))
    ):
        identity = uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO issue_categories(id,code,name,sort_order,is_active,revision) "
                "VALUES (:id,:code,:name,:sort_order,true,1)"
            ),
            {"id": identity, "code": code, "name": name, "sort_order": order},
        )
        connection.execute(
            sa.text(
                "UPDATE issue_categories SET parent_id=:id,revision=revision+1,updated_at=now() "
                "WHERE code IN :codes"
            ).bindparams(sa.bindparam("codes", expanding=True)),
            {"id": identity, "codes": children},
        )
    op.execute("""CREATE FUNCTION issue_history_lock_hierarchy()
    RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      PERFORM pg_advisory_xact_lock(hashtextextended('issue-history-category-hierarchy', 0));
      RETURN NULL;
    END $$""")
    op.execute(
        """CREATE TRIGGER issue_categories_hierarchy_lock
        BEFORE INSERT OR UPDATE OR DELETE ON issue_categories
        FOR EACH STATEMENT EXECUTE FUNCTION issue_history_lock_hierarchy()"""
    )
    op.execute(
        """CREATE TRIGGER issues_category_hierarchy_lock
        BEFORE INSERT OR UPDATE OF category_id ON issues
        FOR EACH STATEMENT EXECUTE FUNCTION issue_history_lock_hierarchy()"""
    )
    op.execute("""CREATE FUNCTION issue_history_check_category()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE parent_parent uuid; parent_active boolean;
    BEGIN
      IF TG_OP = 'UPDATE' AND NEW.parent_id IS NOT DISTINCT FROM OLD.parent_id THEN
        RETURN NEW;
      END IF;
      IF NEW.parent_id IS NULL THEN
        IF EXISTS (SELECT 1 FROM issues WHERE category_id=NEW.id) THEN
          RAISE EXCEPTION 'Assigned issue categories must remain children' USING ERRCODE='23514';
        END IF;
      ELSE
        SELECT parent_id,is_active INTO parent_parent,parent_active
        FROM issue_categories WHERE id=NEW.parent_id;
        IF NOT FOUND OR NEW.parent_id=NEW.id OR parent_parent IS NOT NULL OR NOT parent_active THEN
          RAISE EXCEPTION 'An active root category is required' USING ERRCODE='23514';
        END IF;
        IF EXISTS (SELECT 1 FROM issue_categories WHERE parent_id=NEW.id) THEN
          RAISE EXCEPTION 'Categories with children must remain roots' USING ERRCODE='23514';
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        """CREATE TRIGGER issue_categories_hierarchy_check
        BEFORE INSERT OR UPDATE OF parent_id ON issue_categories
        FOR EACH ROW EXECUTE FUNCTION issue_history_check_category()"""
    )
    op.execute("""CREATE FUNCTION issue_history_check_assignment()
    RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE child_parent uuid; child_active boolean; parent_active boolean;
    BEGIN
      IF TG_OP = 'UPDATE' AND NEW.category_id=OLD.category_id THEN
        RETURN NEW;
      END IF;
      SELECT parent_id,is_active INTO child_parent,child_active
      FROM issue_categories WHERE id=NEW.category_id;
      IF NOT FOUND OR child_parent IS NULL OR NOT child_active THEN
        RAISE EXCEPTION 'An active child category is required' USING ERRCODE='23514';
      END IF;
      SELECT is_active INTO parent_active FROM issue_categories
      WHERE id=child_parent AND parent_id IS NULL;
      IF NOT FOUND OR NOT parent_active THEN
        RAISE EXCEPTION 'An active root category is required' USING ERRCODE='23514';
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        """CREATE TRIGGER issues_category_assignment_check
        BEFORE INSERT OR UPDATE OF category_id ON issues
        FOR EACH ROW EXECUTE FUNCTION issue_history_check_assignment()"""
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER issues_category_assignment_check ON issues")
    op.execute("DROP FUNCTION issue_history_check_assignment()")
    op.execute("DROP TRIGGER issue_categories_hierarchy_check ON issue_categories")
    op.execute("DROP FUNCTION issue_history_check_category()")
    op.execute("DROP TRIGGER issues_category_hierarchy_lock ON issues")
    op.execute("DROP TRIGGER issue_categories_hierarchy_lock ON issue_categories")
    op.execute("DROP FUNCTION issue_history_lock_hierarchy()")
    op.drop_index("ix_issue_categories_parent_id", table_name="issue_categories")
    op.drop_constraint("ck_issue_categories_not_self", "issue_categories", type_="check")
    op.drop_constraint("fk_issue_categories_parent", "issue_categories", type_="foreignkey")
    op.drop_column("issue_categories", "parent_id")
