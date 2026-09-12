"""Only UUID-isolated databases are migrated; legacy grants are preserved."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from alembic import command
from tests.integration.publishing_support import isolated_publishing_database


@pytest.mark.parametrize("mismatch", [False, True])
def test_legacy_grants_and_personal_owner_preflight(
    monkeypatch: pytest.MonkeyPatch,
    mismatch: bool,
) -> None:
    with isolated_publishing_database(monkeypatch) as database:
        command.upgrade(database.config, "0032_evidence_approval_requests")
        engine = create_engine(database.database_url)
        owner, member, newcomer, workspace = uuid4(), uuid4(), uuid4(), uuid4()
        try:
            with engine.begin() as connection:
                for user in (owner, member, newcomer):
                    connection.execute(
                        text("""
                        INSERT INTO users (id, display_name, email, normalized_email,
                            password_hash, role, is_active, created_at, updated_at)
                        VALUES (:id, 'Synthetic', :email, :email, 'synthetic', 'member', true,
                            CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """),
                        {"id": user, "email": f"{user}@example.test"},
                    )
                connection.execute(
                    text("""
                    INSERT INTO workspaces (id, name, kind, created_by, created_at, updated_at)
                    VALUES (:id, 'Synthetic', :kind, :owner, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                    {
                        "id": workspace,
                        "owner": owner,
                        "kind": "personal" if mismatch else "company",
                    },
                )
                for user, role in ((owner, "owner"), (member, "owner" if mismatch else "member")):
                    connection.execute(
                        text("""
                        INSERT INTO workspace_memberships
                            (id, workspace_id, user_id, role, created_at, updated_at)
                        VALUES (:id, :workspace, :user, :role, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """),
                        {"id": uuid4(), "workspace": workspace, "user": user, "role": role},
                    )
            if mismatch:
                with pytest.raises(
                    DBAPIError, match="Personal workspace owner membership mismatch"
                ):
                    command.upgrade(database.config, "head")
                with engine.connect() as connection:
                    assert (
                        connection.scalar(text("SELECT version_num FROM alembic_version"))
                        == "0032_evidence_approval_requests"
                    )
                return
            command.upgrade(database.config, "head")
            with engine.begin() as connection:
                grants = connection.execute(
                    text("""
                    SELECT user_id, can_read, can_write, can_delete, permission_revision
                    FROM workspace_memberships
                """)
                ).all()
                assert {row[0]: tuple(row[1:]) for row in grants} == {
                    owner: (True, True, True, 1),
                    member: (True, True, False, 1),
                }
                connection.execute(
                    text("""
                    INSERT INTO workspace_memberships
                        (id, workspace_id, user_id, role, created_at, updated_at)
                    VALUES (:id, :workspace, :user, 'member', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """),
                    {"id": uuid4(), "workspace": workspace, "user": newcomer},
                )
                assert connection.execute(
                    text("""
                    SELECT can_read, can_write, can_delete, permission_revision
                    FROM workspace_memberships WHERE user_id = :user
                """),
                    {"user": newcomer},
                ).one() == (True, False, False, 1)
            command.downgrade(database.config, "0032_evidence_approval_requests")
            command.upgrade(database.config, "head")
            with engine.begin() as connection:
                connection.execute(
                    text("""
                    INSERT INTO workspace_permission_audits
                        (id, workspace_id, actor_id, target_id, before_permissions,
                         after_permissions, permission_revision, created_at)
                    VALUES (:id, :workspace, :actor, :target, NULL,
                        json_build_object('read',true,'write',false,'delete',false),
                        1, CURRENT_TIMESTAMP)
                """),
                    {"id": uuid4(), "workspace": workspace, "actor": owner, "target": member},
                )
            with pytest.raises(DBAPIError, match="Cannot discard workspace permission history"):
                command.downgrade(database.config, "0032_evidence_approval_requests")
        finally:
            engine.dispose()
