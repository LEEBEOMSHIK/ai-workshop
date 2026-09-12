from uuid import uuid4

import psycopg
import pytest

from alembic import command
from tests.integration.learning_support import isolated_learning_database

pytestmark = pytest.mark.integration


def test_learning_migration_round_trip_preserves_existing_user_and_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_learning_database(monkeypatch) as database:
        command.upgrade(database.config, "0023_rag_domains")
        owner_id = uuid4()
        email = f"{owner_id}@example.test"
        with psycopg.connect(
            database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as connection:
            assert connection.execute("SELECT current_database()").fetchone() == (
                database.name,
            )
            connection.execute(
                """
                INSERT INTO users (
                    id, display_name, email, normalized_email, password_hash,
                    role, is_active
                ) VALUES (%s, 'Sentinel', %s, %s, 'fixture-hash', 'owner', true)
                """,
                (owner_id, email, email),
            )
            connection.commit()

        command.upgrade(database.config, "0024_learning_records")
        with psycopg.connect(
            database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as connection:
            assert connection.execute("SELECT current_database()").fetchone() == (
                database.name,
            )
            assert connection.execute(
                "SELECT display_name FROM users WHERE id = %s", (owner_id,)
            ).fetchone() == ("Sentinel",)
            assert connection.execute("SELECT count(*) FROM learning_records").fetchone() == (
                0,
            )
            assert connection.execute(
                "SELECT count(*) FROM learning_record_revisions"
            ).fetchone() == (0,)
            index_columns = connection.execute(
                """
                SELECT array_agg(a.attname ORDER BY k.ordinality)
                FROM pg_class t
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN pg_index i ON i.indrelid = t.oid
                JOIN pg_class ix ON ix.oid = i.indexrelid
                JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS k(attnum, ordinality)
                    ON true
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
                WHERE n.nspname = 'public'
                  AND t.relname = 'learning_records'
                  AND ix.relname = 'ix_learning_records_owner_updated_id'
                GROUP BY ix.relname
                """
            ).fetchone()
            assert index_columns == (["owner_id", "updated_at", "id"],)
            unique_columns = connection.execute(
                """
                SELECT array_agg(a.attname ORDER BY k.ordinality)
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS k(attnum, ordinality)
                    ON true
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
                WHERE t.relname = 'learning_record_revisions'
                  AND c.contype IN ('p', 'u')
                GROUP BY c.conname
                """
            ).fetchall()
            assert (["record_id", "revision"],) in unique_columns
            foreign_keys = connection.execute(
                """
                SELECT
                    t.relname,
                    c.conname,
                    rt.relname,
                    array_agg(a.attname ORDER BY lk.ordinality),
                    array_agg(ra.attname ORDER BY lk.ordinality),
                    c.condeferrable,
                    c.condeferred,
                    c.confdeltype
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_class rt ON rt.oid = c.confrelid
                JOIN LATERAL unnest(c.conkey) WITH ORDINALITY AS lk(attnum, ordinality)
                    ON true
                JOIN LATERAL unnest(c.confkey) WITH ORDINALITY AS rk(attnum, ordinality)
                    ON rk.ordinality = lk.ordinality
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = lk.attnum
                JOIN pg_attribute ra ON ra.attrelid = rt.oid AND ra.attnum = rk.attnum
                WHERE t.relname IN ('learning_records', 'learning_record_revisions')
                  AND c.contype = 'f'
                GROUP BY
                    t.relname,
                    c.conname,
                    rt.relname,
                    c.condeferrable,
                    c.condeferred,
                    c.confdeltype
                """
            ).fetchall()
            assert (
                "learning_records",
                "learning_records_owner_id_fkey",
                "users",
                ["owner_id"],
                ["id"],
                False,
                False,
                "r",
            ) in foreign_keys
            assert (
                "learning_record_revisions",
                "learning_record_revisions_record_id_fkey",
                "learning_records",
                ["record_id"],
                ["id"],
                False,
                False,
                "r",
            ) in foreign_keys
            assert (
                "learning_records",
                "fk_learning_records_current_revision",
                "learning_record_revisions",
                ["id", "current_revision"],
                ["record_id", "revision"],
                True,
                True,
                "r",
            ) in foreign_keys
            positive_checks = dict(
                connection.execute(
                    """
                    SELECT c.conname, pg_get_constraintdef(c.oid)
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname IN ('learning_records', 'learning_record_revisions')
                      AND c.conname IN (
                          'ck_learning_records_current_revision_positive',
                          'ck_learning_record_revisions_revision_positive'
                      )
                      AND c.contype = 'c'
                    """
                ).fetchall()
            )
            assert set(positive_checks) == {
                "ck_learning_records_current_revision_positive",
                "ck_learning_record_revisions_revision_positive",
            }
            assert "current_revision > 0" in positive_checks[
                "ck_learning_records_current_revision_positive"
            ]
            assert "revision > 0" in positive_checks[
                "ck_learning_record_revisions_revision_positive"
            ]

        command.downgrade(database.config, "0023_rag_domains")
        with psycopg.connect(
            database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.learning_records')"
            ).fetchone() == (None,)
            assert connection.execute(
                "SELECT to_regclass('public.learning_record_revisions')"
            ).fetchone() == (None,)
            assert connection.execute(
                "SELECT display_name FROM users WHERE id = %s", (owner_id,)
            ).fetchone() == ("Sentinel",)

        command.upgrade(database.config, "0024_learning_records")
        with psycopg.connect(
            database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        ) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "0024_learning_records",
            )
            assert connection.execute(
                "SELECT display_name FROM users WHERE id = %s", (owner_id,)
            ).fetchone() == ("Sentinel",)
            assert connection.execute("SELECT count(*) FROM learning_records").fetchone() == (
                0,
            )
