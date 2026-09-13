"""Reserve normalized folder names only for active folders."""

import sqlalchemy as sa

from ai_workshop.platform.assets.trash_migration_preflight import (
    assert_trash_migration_ready,
)
from alembic import op

revision = "0037_active_folder_names"
down_revision = "0036_asset_purge_jobs"
branch_labels = None
depends_on = None

# Frozen v1 snapshot. Historical DDL must not import a future normalization rule.
_FOLDER_NAME_WHITESPACE_SQL = (
    r"U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F"
    r"\0020\0085\00A0\1680\2000\2001\2002\2003\2004"
    r"\2005\2006\2007\2008\2009\200A\2028\2029\202F"
    r"\205F\3000'"
)
_OLD_UNIQUE = "folders_workspace_id_parent_id_name_key"


def _assert_old_unique_shape(connection: sa.engine.Connection) -> None:
    columns = connection.exec_driver_sql(
        """
        SELECT array_agg(attribute.attname ORDER BY key.ordinality)
        FROM pg_constraint AS constraint_record
        JOIN LATERAL unnest(constraint_record.conkey)
          WITH ORDINALITY AS key(attnum, ordinality) ON true
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = constraint_record.conrelid
         AND attribute.attnum = key.attnum
        WHERE constraint_record.conrelid = 'folders'::regclass
          AND constraint_record.conname = %s
          AND constraint_record.contype = 'u'
        GROUP BY constraint_record.oid
        """,
        (_OLD_UNIQUE,),
    ).scalar_one_or_none()
    if tuple(columns or ()) != ("workspace_id", "parent_id", "name"):
        raise RuntimeError("asset_folder_name_constraint_mismatch")


def _has_downgrade_usage(connection: sa.engine.Connection) -> bool:
    return bool(
        connection.exec_driver_sql(
            """
            SELECT
              EXISTS (SELECT 1 FROM asset_retention_policies)
              OR EXISTS (SELECT 1 FROM asset_trash_batches)
              OR EXISTS (SELECT 1 FROM asset_purge_jobs)
              OR EXISTS (SELECT 1 FROM asset_purge_dispatches)
              OR EXISTS (
                SELECT 1 FROM folders
                WHERE lifecycle <> 'active' OR lifecycle_generation <> 1
                   OR trash_batch_id IS NOT NULL OR trashed_at IS NOT NULL
                   OR purge_after IS NOT NULL
              )
              OR EXISTS (
                SELECT 1 FROM documents
                WHERE lifecycle <> 'active' OR lifecycle_generation <> 1
                   OR trash_batch_id IS NOT NULL OR trashed_at IS NOT NULL
                   OR purge_after IS NOT NULL
              )
            """
        ).scalar_one()
    )


def _old_unique_can_be_restored(connection: sa.engine.Connection) -> bool:
    return not bool(
        connection.exec_driver_sql(
            """
            SELECT EXISTS (
              SELECT 1
              FROM folders
              WHERE parent_id IS NOT NULL
              GROUP BY workspace_id, parent_id, name
              HAVING count(*) > 1
            )
            """
        ).scalar_one()
    )


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE folders, documents IN SHARE ROW EXCLUSIVE MODE"
    )
    assert_trash_migration_ready(connection)
    _assert_old_unique_shape(connection)

    op.drop_constraint(_OLD_UNIQUE, "folders", type_="unique")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX ix_folders_active_root_name "
        f"ON folders (workspace_id, btrim(name, {_FOLDER_NAME_WHITESPACE_SQL})) "
        "WHERE lifecycle = 'active' AND parent_id IS NULL"
    )
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX ix_folders_active_sibling_name "
        f"ON folders (workspace_id, parent_id, btrim(name, {_FOLDER_NAME_WHITESPACE_SQL})) "
        "WHERE lifecycle = 'active' AND parent_id IS NOT NULL"
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE folders, documents, asset_retention_policies, asset_trash_batches, "
        "asset_purge_jobs, asset_purge_dispatches IN SHARE ROW EXCLUSIVE MODE"
    )
    if _has_downgrade_usage(connection):
        raise RuntimeError("asset_folder_name_downgrade_unsafe")
    if not _old_unique_can_be_restored(connection):
        raise RuntimeError("asset_folder_name_unique_restore_unsafe")

    op.drop_index("ix_folders_active_sibling_name", table_name="folders")
    op.drop_index("ix_folders_active_root_name", table_name="folders")
    op.create_unique_constraint(
        _OLD_UNIQUE,
        "folders",
        ["workspace_id", "parent_id", "name"],
    )
