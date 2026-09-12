from __future__ import annotations

import psycopg
import pytest

from alembic import command
from tests.integration.publishing_support import isolated_publishing_database

pytestmark = pytest.mark.integration


def test_publishing_migration_round_trip_is_additive_and_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0024_learning_records")
        command.upgrade(database.config, "0025_publishing")

        url = database.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        with psycopg.connect(url) as connection:
            assert connection.execute("SELECT current_database()").fetchone() == (
                database.name,
            )
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0025_publishing",)
            assert connection.execute(
                "SELECT to_regclass('public.learning_records')"
            ).fetchone() == ("learning_records",)
            for table in (
                "publishing_studies",
                "publishing_revisions",
                "publishing_commands",
            ):
                assert connection.execute(
                    "SELECT to_regclass(%s)", (f"public.{table}",)
                ).fetchone() == (table,)

            constraints = {
                row[0]
                for row in connection.execute(
                    """
                    SELECT c.conname
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname IN (
                        'publishing_studies',
                        'publishing_revisions',
                        'publishing_commands'
                    )
                    """
                ).fetchall()
            }
            assert {
                "pk_publishing_studies",
                "pk_publishing_revisions",
                "pk_publishing_commands",
                "uq_publishing_commands_slug_sequence",
                "fk_publishing_revisions_study",
                "fk_publishing_commands_study",
                "ck_publishing_studies_sequence_nonnegative",
                "ck_publishing_studies_applied_state",
                "ck_publishing_commands_action_payload",
                "ck_publishing_commands_receipt_state",
            } <= constraints

        command.downgrade(database.config, "0024_learning_records")
        with psycopg.connect(url) as connection:
            for table in (
                "publishing_commands",
                "publishing_revisions",
                "publishing_studies",
            ):
                assert connection.execute(
                    "SELECT to_regclass(%s)", (f"public.{table}",)
                ).fetchone() == (None,)
            assert connection.execute(
                "SELECT to_regclass('public.learning_records')"
            ).fetchone() == ("learning_records",)
