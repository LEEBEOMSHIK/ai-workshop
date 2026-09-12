import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_workshop.platform.publishing.domain import PublicationAction, PublicationCommand
from ai_workshop.platform.publishing.package import StudyContent, StudySnapshot, snapshot_digest
from ai_workshop.platform.publishing.public_store import (
    SqlitePublicStudyReader,
    SqlitePublicStudyWriter,
)
from ai_workshop.public_app import create_public_app


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    for index in reversed(range(26)):
        slug = f"study-{index:02d}"
        snapshot = StudySnapshot(
            revision=1,
            content=StudyContent(
                slug=slug, title="Synthetic study", summary="Synthetic summary",
                body="Synthetic body", verification="Synthetic checks",
                limitations="Synthetic data only",
                topic_keys=("rag", "retrieval") if index % 2 == 0 else ("rag-other",),
            ),
        )
        writer.apply(PublicationCommand(
            slug=slug, sequence=1, request_id=f"publish-{slug}",
            action=PublicationAction.PUBLISH, snapshot=snapshot, digest=snapshot_digest(snapshot),
        ))
    writer.apply(PublicationCommand(
        slug="study-25", sequence=2, request_id="withdraw-25",
        action=PublicationAction.WITHDRAW, snapshot=None, digest=None,
    ))
    # Even a stale withdrawn topic must not enter facets or item counts.
    with sqlite3.connect(path) as connection:
        connection.execute("INSERT INTO public_study_topics VALUES ('study-25', 'withdrawn')")
    return path


def test_catalog_pages_filter_before_slicing_and_keep_global_facets(catalog_path: Path) -> None:
    with TestClient(create_public_app(reader=SqlitePublicStudyReader(catalog_path))) as client:
        first = client.get("/api/public/study-catalog")
        second = client.get("/api/public/study-catalog?page=2")
        last = client.get("/api/public/study-catalog?page=1000000")
        filtered = client.get("/api/public/study-catalog?page=2&topic_key=rag")
        empty = client.get("/api/public/study-catalog?page=9&topic_key=missing")
    for response in (first, second, last, filtered, empty):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["topics"] == [
            {"key": "rag", "count": 13}, {"key": "rag-other", "count": 12},
            {"key": "retrieval", "count": 13},
        ]
    assert [i["content"]["slug"] for i in first.json()["items"]] == [
        f"study-{i:02d}" for i in range(12)
    ]
    assert [i["content"]["slug"] for i in second.json()["items"]] == [
        f"study-{i:02d}" for i in range(12, 24)
    ]
    assert (first.json()["total"], first.json()["page_size"], first.json()["total_pages"]) == (
        25, 12, 3,
    )
    assert last.json()["page"] == 3
    assert [i["content"]["slug"] for i in last.json()["items"]] == ["study-24"]
    assert filtered.json()["total"] == 13
    assert filtered.json()["total_pages"] == 2
    assert [i["content"]["slug"] for i in filtered.json()["items"]] == ["study-24"]
    assert (empty.json()["items"], empty.json()["total"], empty.json()["page"],
            empty.json()["total_pages"]) == ([], 0, 1, 0)


@pytest.mark.parametrize("query", [
    "page=0", "page=-1", "page=1.5", "page=oops", "page=1000001",
    "topic_key=", "topic_key=RAG", "topic_key=rag%00", "topic_key=rag--x",
    "topic_key=" + "a" * 129,
])
def test_catalog_rejects_invalid_query(catalog_path: Path, query: str) -> None:
    with TestClient(create_public_app(reader=SqlitePublicStudyReader(catalog_path))) as client:
        response = client.get(f"/api/public/study-catalog?{query}")
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("corruption", ["payload", "topic"])
def test_catalog_fails_closed_for_selected_corruption_only(
    catalog_path: Path, corruption: str,
) -> None:
    with sqlite3.connect(catalog_path) as connection:
        if corruption == "payload":
            connection.execute(
                "UPDATE public_study_projections SET payload = ? WHERE slug = 'study-24'",
                (b"synthetic-corrupt-marker",),
            )
        else:
            connection.execute("DELETE FROM public_study_topics WHERE slug = 'study-24'")
            connection.execute("INSERT INTO public_study_topics VALUES ('study-24', 'wrong')")
    with TestClient(create_public_app(reader=SqlitePublicStudyReader(catalog_path))) as client:
        first = client.get("/api/public/study-catalog")
        corrupt = client.get("/api/public/study-catalog?page=3")
    assert first.status_code == 200  # Off-page payloads are never decoded.
    assert corrupt.status_code == 503
    assert corrupt.json()["error"]["code"] == "publishing_store_unavailable"
    assert "synthetic-corrupt-marker" not in corrupt.text


@pytest.mark.parametrize("state", ["missing", "schema-missing", "locked"])
def test_catalog_unavailable_store_is_503_without_creation(tmp_path: Path, state: str) -> None:
    path = tmp_path / "catalog.sqlite3"
    connection = None
    if state == "schema-missing":
        connection = sqlite3.connect(path)
    elif state == "locked":
        SqlitePublicStudyWriter(path).initialize()
        connection = sqlite3.connect(path)
        connection.execute("BEGIN EXCLUSIVE")
    try:
        with TestClient(create_public_app(reader=SqlitePublicStudyReader(path))) as client:
            response = client.get("/api/public/study-catalog")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "publishing_store_unavailable"
        assert str(path) not in response.text
        if state == "missing":
            assert not path.exists()
    finally:
        if connection is not None:
            connection.close()


def test_catalog_counts_facets_and_items_share_a_read_snapshot(catalog_path: Path) -> None:
    with sqlite3.connect(catalog_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")

    class ConcurrentWithdrawalReader(SqlitePublicStudyReader):
        def _connect(self) -> sqlite3.Connection:
            connection = super()._connect()

            def withdraw_between_reads(statement: str) -> None:
                if "COUNT(DISTINCT projection.slug)" in statement:
                    SqlitePublicStudyWriter(catalog_path).apply(PublicationCommand(
                        slug="study-24", sequence=2, request_id="concurrent-withdrawal",
                        action=PublicationAction.WITHDRAW, snapshot=None, digest=None,
                    ))

            connection.set_trace_callback(withdraw_between_reads)
            return connection

    catalog = ConcurrentWithdrawalReader(catalog_path).catalog(page=3)
    assert catalog.total == 25
    assert catalog.page == 3
    assert [item.content.slug for item in catalog.items] == ["study-24"]
    assert [(topic.key, topic.count) for topic in catalog.topics] == [
        ("rag", 13), ("rag-other", 12), ("retrieval", 13),
    ]
    assert SqlitePublicStudyReader(catalog_path).catalog().total == 24
