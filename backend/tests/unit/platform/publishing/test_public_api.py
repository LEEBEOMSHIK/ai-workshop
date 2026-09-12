from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from ai_workshop.platform.publishing.domain import PublicationAction, PublicationCommand
from ai_workshop.platform.publishing.package import StudyContent, StudySnapshot, snapshot_digest
from ai_workshop.platform.publishing.public_store import (
    SqlitePublicStudyReader,
    SqlitePublicStudyWriter,
)
from ai_workshop.public_app import create_public_app


class ExplodingPublicReader:
    def get(self, slug: str) -> StudySnapshot:
        del slug
        raise RuntimeError("private-public-reader-marker")

    def list_published(self, topic_key: str | None = None) -> tuple[StudySnapshot, ...]:
        del topic_key
        raise RuntimeError("private-public-reader-marker")


def publish_command(
    slug: str,
    *,
    sequence: int = 1,
    request_id: str | None = None,
    topic_keys: tuple[str, ...] = ("rag",),
) -> PublicationCommand:
    snapshot = StudySnapshot(
        revision=1,
        content=StudyContent(
            slug=slug,
            title=f"Study {slug}",
            summary="Public summary.",
            topic_keys=topic_keys,
            body="Public body.",
            verification="Fixture verification.",
            limitations="Synthetic only.",
        ),
    )
    return PublicationCommand(
        slug=slug,
        sequence=sequence,
        request_id=request_id or f"publish-{slug}",
        action=PublicationAction.PUBLISH,
        snapshot=snapshot,
        digest=snapshot_digest(snapshot),
    )


def test_public_app_needs_no_private_secret_or_database_and_reads_sqlite(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("AI_WORKSHOP_SECRET_KEY", raising=False)
    monkeypatch.delenv("AI_WORKSHOP_DATABASE_URL", raising=False)
    path = tmp_path / "public.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command("zebra-study", topic_keys=("rag", "retrieval")))
    writer.apply(publish_command("alpha-study", topic_keys=("evaluation",)))
    app = create_public_app(reader=SqlitePublicStudyReader(path))

    with TestClient(app) as client:
        health = client.get("/api/public/health")
        listed = client.get("/api/public/studies")
        filtered = client.get("/api/public/studies?topic_key=rag")
        detail = client.get("/api/public/studies/zebra-study")

    assert health.json() == {"status": "ok"}
    assert [item["content"]["slug"] for item in listed.json()["items"]] == [
        "alpha-study",
        "zebra-study",
    ]
    assert [item["content"]["slug"] for item in filtered.json()["items"]] == [
        "zebra-study"
    ]
    assert detail.json()["content"]["slug"] == "zebra-study"
    for forbidden in ("request_id", "digest", "source_path", "owner_id"):
        assert forbidden not in detail.text
    for response in (health, listed, filtered, detail):
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"


def test_public_missing_withdrawn_and_corrupt_details_share_safe_404(
    tmp_path: Path,
) -> None:
    path = tmp_path / "public.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command("withdrawn-study"))
    writer.apply(
        PublicationCommand(
            slug="withdrawn-study",
            sequence=2,
            request_id="withdraw-withdrawn-study",
            action=PublicationAction.WITHDRAW,
            snapshot=None,
            digest=None,
        )
    )
    writer.apply(publish_command("corrupt-study"))
    marker = "private-corrupt-marker"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE public_study_projections SET payload = ? WHERE slug = ?",
            (marker.encode(), "corrupt-study"),
        )
    app = create_public_app(reader=SqlitePublicStudyReader(path))

    with TestClient(app) as client:
        responses = tuple(
            client.get(f"/api/public/studies/{slug}")
            for slug in ("missing-study", "withdrawn-study", "corrupt-study")
        )

    for response in responses:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
        assert response.headers["cache-control"] == "no-store"
        assert marker not in response.text


def test_public_malformed_keys_are_safe_at_the_sqlite_boundary(tmp_path: Path) -> None:
    path = tmp_path / "public.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command("valid-study"))
    app = create_public_app(reader=SqlitePublicStudyReader(path))

    with TestClient(app) as client:
        invalid_topic = client.get(
            "/api/public/studies",
            params={"topic_key": "private\x00topic"},
        )
        invalid_slug = client.get("/api/public/studies/private%00study")

    assert invalid_topic.status_code == 200
    assert invalid_topic.json() == {"items": []}
    assert invalid_slug.status_code == 404
    assert invalid_slug.json()["error"]["code"] == "not_found"
    for response in (invalid_topic, invalid_slug):
        assert response.headers["cache-control"] == "no-store"


def test_public_unexpected_reader_error_is_safe_and_no_store() -> None:
    app = create_public_app(reader=ExplodingPublicReader())  # type: ignore[arg-type]

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/public/studies/example-study")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_server_error"
    assert response.headers["cache-control"] == "no-store"
    assert "private-public-reader-marker" not in response.text
