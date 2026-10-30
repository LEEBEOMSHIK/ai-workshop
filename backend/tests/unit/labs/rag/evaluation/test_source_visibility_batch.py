import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.evaluation.generative_read import visible_run


def source(identity):
    return dict(zip(
        ("document_id", "asset_version_id", "projection_id"), map(str, identity), strict=True,
    ))


def triples(count):
    return [(UUID(int=3 * n + 1), UUID(int=3 * n + 2), UUID(int=3 * n + 3)) for n in range(count)]


class Session:
    def __init__(self, available):
        self.available = set(available)
        self.statements = []
        self.batch_sizes = []
        self.failure = None
        self.transform = lambda rows: rows

    async def execute(self, statement):
        self.statements.append(statement)
        if self.failure:
            raise self.failure
        params = statement.compile().params
        expected = next(value for value in params.values() if isinstance(value, list))
        self.batch_sizes.append(len(expected))
        actual = self.transform([item for item in expected if item in self.available])
        return SimpleNamespace(all=lambda: actual)

    async def scalar(self, statement):
        self.statements.append(statement)
        if self.failure:
            raise self.failure
        values = set(statement.compile().params.values())
        return next((item[0] for item in self.available if set(item) <= values), None)


@pytest.mark.parametrize("count,queries", [(1, 1), (64, 1), (65, 2), (129, 3)])
async def test_exact_source_query_count_is_bounded(count, queries):
    identities = triples(count)
    actor = uuid4()
    run = SimpleNamespace(owner_id=actor, snapshot={"sources": list(map(source, identities))})
    session = Session(identities)
    assert await visible_run(session, actor, run)
    assert len(session.statements) == queries
    assert max(session.batch_sizes) <= 64
    for statement in session.statements:
        sql = str(statement)
        assert len(statement.selected_columns) == 3
        assert "rag_index_builds" not in sql and "active_version_id" not in sql
        assert "lifecycle" in sql and "workspace_memberships" in sql and "is_active" in sql
        assert "rag_document_projections.status" in sql and "asset_versions.status" in sql
        assert actor in statement.compile().params.values()


@pytest.mark.parametrize("owner_matches", [False, True])
async def test_wrong_owner_and_empty_do_not_query(owner_matches):
    actor = uuid4()
    run = SimpleNamespace(owner_id=actor if owner_matches else uuid4(), snapshot={})
    session = Session([])
    assert await visible_run(session, actor, run) is owner_matches
    assert not session.statements


@pytest.mark.parametrize("wrong", ["missing", "crossed", "extra"])
async def test_full_tuple_set_must_match_not_independent_id_sets(wrong):
    actor = uuid4()
    a, b = triples(2)
    run = SimpleNamespace(owner_id=actor, snapshot=[source(a), source(b)])
    session = Session([a, b])
    if wrong == "missing":
        session.transform = lambda rows: rows[:1]
    elif wrong == "crossed":
        session.transform = lambda rows: [(a[0], b[1], a[2]), (b[0], a[1], b[2])]
    else:
        session.transform = lambda rows: rows + [(uuid4(), uuid4(), uuid4())]
    assert not await visible_run(session, actor, run)


async def test_nested_duplicate_sources_and_duplicate_sql_rows_use_set_semantics():
    actor = uuid4()
    identity = triples(1)[0]
    run = SimpleNamespace(owner_id=actor, snapshot={"partial": {
        "document_id": "ignored", "child": [source(identity), {"nested": source(identity)}],
    }})
    session = Session([identity])
    session.transform = lambda rows: rows + rows
    assert await visible_run(session, actor, run)
    assert session.batch_sizes == [1]


async def test_next_checkpoint_reextracts_nested_sources_and_rechecks_revocation():
    actor = uuid4()
    a, b = triples(2)
    run = SimpleNamespace(owner_id=actor, snapshot={"nested": [source(a)]})
    session = Session([a, b])
    assert await visible_run(session, actor, run)
    run.snapshot["nested"].append(source(b))
    session.available.remove(b)
    assert not await visible_run(session, actor, run)
    assert session.batch_sizes == [1, 2]


async def test_malformed_uuid_still_fails_before_sql():
    actor = uuid4()
    run = SimpleNamespace(owner_id=actor, snapshot=source(triples(1)[0]))
    run.snapshot["document_id"] = "bad"
    session = Session([])
    with pytest.raises(ValueError):
        await visible_run(session, actor, run)
    assert not session.statements


@pytest.mark.parametrize("failure", [RuntimeError("synthetic"), asyncio.CancelledError()])
async def test_sql_error_and_cancellation_propagate_unchanged(failure):
    actor = uuid4()
    identities = triples(1)
    run = SimpleNamespace(owner_id=actor, snapshot=list(map(source, identities)))
    session = Session(identities)
    session.failure = failure
    with pytest.raises(type(failure)) as caught:
        await visible_run(session, actor, run)
    assert caught.value is failure
