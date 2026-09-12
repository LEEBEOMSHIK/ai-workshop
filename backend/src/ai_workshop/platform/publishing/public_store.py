from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from ai_workshop.platform.publishing.domain import PublicationAction, PublicationCommand
from ai_workshop.platform.publishing.package import (
    StudySnapshot,
    canonical_bytes,
    decode_snapshot,
)
from ai_workshop.platform.publishing.projection import PublicStudyProjection
from ai_workshop.platform.publishing.schemas import PublicStudyCatalog, PublicStudyTopicCount
from ai_workshop.shared.errors import AppError

_PUBLIC_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _is_public_key(value: object) -> bool:
    return isinstance(value, str) and _PUBLIC_KEY.fullmatch(value) is not None


def _command_conflict() -> AppError:
    return AppError(
        "publishing_command_conflict",
        "The publication command conflicts.",
        409,
    )


def _not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)


def _store_unavailable() -> AppError:
    return AppError(
        "publishing_store_unavailable",
        "The public study store is unavailable.",
        503,
    )


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    slug: str
    sequence: int
    request_id: str
    action: PublicationAction


def _receipt(command: PublicationCommand) -> PublicationReceipt:
    return PublicationReceipt(
        slug=command.slug,
        sequence=command.sequence,
        request_id=command.request_id,
        action=command.action,
    )


def _validated_command(command: PublicationCommand) -> PublicationCommand:
    if type(command) is not PublicationCommand:
        raise _command_conflict()
    try:
        validated = PublicationCommand(
            slug=command.slug,
            sequence=command.sequence,
            request_id=command.request_id,
            action=command.action,
            snapshot=command.snapshot,
            digest=command.digest,
        )
        validated.request_id.encode("utf-8")
        PublicStudyProjection(slug=validated.slug).apply(validated)
    except (AppError, AttributeError, TypeError, ValueError):
        raise _command_conflict() from None
    return validated


def _command_fingerprint(command: PublicationCommand) -> str:
    identity = json.dumps(
        {
            "action": command.action.value,
            "digest": command.digest,
            "request_id": command.request_id,
            "sequence": command.sequence,
            "slug": command.slug,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()


class SqlitePublicStudyWriter:
    def __init__(self, path: Path) -> None:
        self._path = path

    def initialize(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self._path)) as connection, connection:
                connection.execute("PRAGMA foreign_keys = ON")
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS public_study_projections (
                        slug TEXT PRIMARY KEY,
                        sequence INTEGER NOT NULL CHECK (sequence > 0),
                        request_id TEXT NOT NULL,
                        action TEXT NOT NULL CHECK (action IN ('publish', 'withdraw')),
                        payload BLOB,
                        digest TEXT,
                        CHECK (
                            (action = 'publish' AND payload IS NOT NULL AND digest IS NOT NULL)
                            OR
                            (action = 'withdraw' AND payload IS NULL AND digest IS NULL)
                        )
                    );

                    CREATE TABLE IF NOT EXISTS public_study_topics (
                        slug TEXT NOT NULL REFERENCES public_study_projections(slug)
                            ON DELETE CASCADE,
                        topic_key TEXT NOT NULL,
                        PRIMARY KEY (slug, topic_key)
                    );

                    CREATE TABLE IF NOT EXISTS public_request_history (
                        request_id TEXT PRIMARY KEY,
                        fingerprint TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS ix_public_study_topics_topic_slug
                    ON public_study_topics(topic_key, slug);
                    """
                )
        except (OSError, UnicodeError, sqlite3.Error):
            raise _store_unavailable() from None

    def apply(self, command: PublicationCommand) -> PublicationReceipt:
        validated = _validated_command(command)
        fingerprint = _command_fingerprint(validated)
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(self._path, isolation_level=None)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            previous_fingerprint = connection.execute(
                "SELECT fingerprint FROM public_request_history WHERE request_id = ?",
                (validated.request_id,),
            ).fetchone()
            if previous_fingerprint is not None:
                if previous_fingerprint == (fingerprint,):
                    connection.rollback()
                    return _receipt(validated)
                raise _command_conflict()

            current = self._load_projection(connection, validated.slug)
            updated = current.apply(validated)
            payload = canonical_bytes(updated.snapshot) if updated.snapshot is not None else None
            connection.execute(
                """
                INSERT INTO public_study_projections
                    (slug, sequence, request_id, action, payload, digest)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(slug) DO UPDATE SET
                    sequence = excluded.sequence,
                    request_id = excluded.request_id,
                    action = excluded.action,
                    payload = excluded.payload,
                    digest = excluded.digest
                """,
                (
                    validated.slug,
                    validated.sequence,
                    validated.request_id,
                    validated.action.value,
                    sqlite3.Binary(payload) if payload is not None else None,
                    validated.digest,
                ),
            )
            connection.execute(
                "DELETE FROM public_study_topics WHERE slug = ?",
                (validated.slug,),
            )
            if updated.snapshot is not None:
                connection.executemany(
                    "INSERT INTO public_study_topics (slug, topic_key) VALUES (?, ?)",
                    ((validated.slug, topic) for topic in updated.snapshot.content.topic_keys),
                )
            connection.execute(
                "INSERT INTO public_request_history (request_id, fingerprint) VALUES (?, ?)",
                (validated.request_id, fingerprint),
            )
            connection.commit()
            return _receipt(validated)
        except AppError:
            if connection is not None:
                connection.rollback()
            raise
        except (OSError, UnicodeError, sqlite3.Error):
            if connection is not None:
                connection.rollback()
            raise _store_unavailable() from None
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _load_projection(
        connection: sqlite3.Connection,
        slug: str,
    ) -> PublicStudyProjection:
        row = connection.execute(
            """
            SELECT sequence, request_id, action, payload, digest
            FROM public_study_projections
            WHERE slug = ?
            """,
            (slug,),
        ).fetchone()
        if row is None:
            return PublicStudyProjection(slug=slug)

        sequence, request_id, action_value, payload, digest = row
        try:
            action = PublicationAction(action_value)
            snapshot = None
            if action is PublicationAction.PUBLISH:
                if not isinstance(payload, bytes) or not isinstance(digest, str):
                    raise _store_unavailable()
                snapshot = decode_snapshot(payload, expected_digest=digest)
                if snapshot.content.slug != slug:
                    raise _store_unavailable()
            elif payload is not None or digest is not None:
                raise _store_unavailable()
            last_command = PublicationCommand(
                slug=slug,
                sequence=sequence,
                request_id=request_id,
                action=action,
                snapshot=snapshot,
                digest=digest,
            )
            return PublicStudyProjection(
                slug=slug,
                sequence=sequence,
                last_command=last_command,
                snapshot=snapshot,
            )
        except (AppError, TypeError, ValueError):
            raise _store_unavailable() from None


class SqlitePublicStudyReader:
    def __init__(self, path: Path) -> None:
        self._path = path

    def catalog(self, *, page: int = 1, topic_key: str | None = None) -> PublicStudyCatalog:
        page_size = 12
        predicate = "projection.action = ?"
        parameters: tuple[str, ...] = (PublicationAction.PUBLISH.value,)
        if topic_key is not None:
            predicate += """ AND EXISTS (
                SELECT 1 FROM public_study_topics AS topic
                WHERE topic.slug = projection.slug AND topic.topic_key = ?
            )"""
            parameters += (topic_key,)
        try:
            with closing(self._connect()) as connection:
                # Hold one SQLite snapshot across count, global facets and page rows.
                connection.execute("BEGIN")
                total = connection.execute(
                    "SELECT COUNT(*) FROM public_study_projections AS projection "
                    f"WHERE {predicate}",
                    parameters,
                ).fetchone()[0]
                total_pages = (total + page_size - 1) // page_size
                current_page = min(max(page, 1), max(total_pages, 1))
                topics = tuple(
                    PublicStudyTopicCount(key=key, count=count)
                    for key, count in connection.execute(
                        """
                        SELECT topic.topic_key, COUNT(DISTINCT projection.slug)
                        FROM public_study_topics AS topic
                        JOIN public_study_projections AS projection ON projection.slug = topic.slug
                        WHERE projection.action = ?
                        GROUP BY topic.topic_key ORDER BY topic.topic_key
                        """,
                        (PublicationAction.PUBLISH.value,),
                    )
                )
                rows = connection.execute(
                    f"""
                    SELECT projection.slug, projection.payload, projection.digest
                    FROM public_study_projections AS projection WHERE {predicate}
                    ORDER BY projection.slug LIMIT ? OFFSET ?
                    """,
                    (*parameters, page_size, (current_page - 1) * page_size),
                ).fetchall()
                snapshots: list[StudySnapshot] = []
                for row in rows:
                    snapshot = self._decode_row(row)
                    if snapshot is None:
                        raise _store_unavailable()
                    stored_topics = {
                        topic[0] for topic in connection.execute(
                            "SELECT topic_key FROM public_study_topics WHERE slug = ?", (row[0],)
                        )
                    }
                    if stored_topics != set(snapshot.content.topic_keys):
                        raise _store_unavailable()
                    snapshots.append(snapshot)
                return PublicStudyCatalog(
                    items=tuple(snapshots), total=total, page=current_page,
                    total_pages=total_pages, topics=topics,
                )
        except (OSError, sqlite3.Error):
            raise _store_unavailable() from None

    def get(self, slug: str) -> StudySnapshot:
        if not _is_public_key(slug):
            self._require_projection_schema()
            raise _not_found()
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """
                    SELECT slug, payload, digest
                    FROM public_study_projections
                    WHERE slug = ? AND action = ?
                    """,
                    (slug, PublicationAction.PUBLISH.value),
                ).fetchone()
        except (OSError, sqlite3.Error):
            raise _store_unavailable() from None
        if row is None:
            raise _not_found()
        snapshot = self._decode_row(row)
        if snapshot is None:
            raise _not_found()
        return snapshot

    def list_published(self, topic_key: str | None = None) -> tuple[StudySnapshot, ...]:
        if topic_key is not None and not _is_public_key(topic_key):
            self._require_topic_schema()
            return ()
        try:
            with closing(self._connect()) as connection:
                if topic_key is None:
                    rows = connection.execute(
                        """
                        SELECT slug, payload, digest
                        FROM public_study_projections
                        WHERE action = ?
                        ORDER BY slug
                        """,
                        (PublicationAction.PUBLISH.value,),
                    ).fetchall()
                else:
                    rows = connection.execute(
                        """
                        SELECT projection.slug, projection.payload, projection.digest
                        FROM public_study_projections AS projection
                        WHERE projection.action = ?
                          AND EXISTS (
                              SELECT 1
                              FROM public_study_topics AS topic
                              WHERE topic.slug = projection.slug AND topic.topic_key = ?
                          )
                        ORDER BY projection.slug
                        """,
                        (PublicationAction.PUBLISH.value, topic_key),
                    ).fetchall()
        except (OSError, sqlite3.Error):
            raise _store_unavailable() from None

        snapshots: list[StudySnapshot] = []
        for row in rows:
            snapshot = self._decode_row(row)
            if snapshot is None:
                continue
            if topic_key is not None and topic_key not in snapshot.content.topic_keys:
                continue
            snapshots.append(snapshot)
        return tuple(snapshots)

    def _require_projection_schema(self) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    "SELECT 1 FROM public_study_projections LIMIT 0"
                ).fetchall()
        except (OSError, sqlite3.Error):
            raise _store_unavailable() from None

    def _require_topic_schema(self) -> None:
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """
                    SELECT 1
                    FROM public_study_projections AS projection
                    JOIN public_study_topics AS topic ON topic.slug = projection.slug
                    LIMIT 0
                    """
                ).fetchall()
        except (OSError, sqlite3.Error):
            raise _store_unavailable() from None

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self._path.resolve().as_uri()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        try:
            connection.execute("PRAGMA query_only = ON")
        except sqlite3.Error:
            connection.close()
            raise
        return connection

    @staticmethod
    def _decode_row(row: tuple[object, ...]) -> StudySnapshot | None:
        slug, payload, digest = row
        if (
            not isinstance(slug, str)
            or not isinstance(payload, bytes)
            or not isinstance(digest, str)
        ):
            return None
        try:
            snapshot = decode_snapshot(payload, expected_digest=digest)
        except AppError:
            return None
        if snapshot.content.slug != slug:
            return None
        return snapshot
