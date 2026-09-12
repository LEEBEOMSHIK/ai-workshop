import sqlite3
from pathlib import Path

import pytest

from ai_workshop.platform.publishing.domain import PublicationAction, PublicationCommand
from ai_workshop.platform.publishing.package import (
    StudyContent,
    StudySnapshot,
    canonical_bytes,
    snapshot_digest,
)
from ai_workshop.platform.publishing.public_store import (
    PublicationReceipt,
    SqlitePublicStudyReader,
    SqlitePublicStudyWriter,
)
from ai_workshop.shared.errors import AppError


def synthetic_snapshot(
    *,
    slug: str = "example-study",
    title: str = "합성 연구",
    topic_keys: tuple[str, ...] = ("rag",),
) -> StudySnapshot:
    return StudySnapshot(
        revision=1,
        content=StudyContent(
            slug=slug,
            title=title,
            summary="공개 저장 계약을 검증하는 합성 요약",
            topic_keys=topic_keys,
            body="공개 저장 계약을 검증하는 합성 본문",
            verification="재시작 뒤 승인된 게시본을 확인함",
            limitations="실제 자료와 외부 서비스를 사용하지 않음",
        ),
    )


def publish_command(
    *,
    slug: str = "example-study",
    sequence: int = 1,
    request_id: str = "publish-request",
    title: str = "합성 연구",
    topic_keys: tuple[str, ...] = ("rag",),
) -> PublicationCommand:
    snapshot = synthetic_snapshot(slug=slug, title=title, topic_keys=topic_keys)
    return PublicationCommand(
        slug=slug,
        sequence=sequence,
        request_id=request_id,
        action=PublicationAction.PUBLISH,
        snapshot=snapshot,
        digest=snapshot_digest(snapshot),
    )


def withdraw_command(
    *,
    slug: str = "example-study",
    sequence: int = 2,
    request_id: str = "withdraw-request",
) -> PublicationCommand:
    return PublicationCommand(
        slug=slug,
        sequence=sequence,
        request_id=request_id,
        action=PublicationAction.WITHDRAW,
        snapshot=None,
        digest=None,
    )


def test_published_snapshot_survives_writer_and_reader_reopen(tmp_path: Path) -> None:
    path = tmp_path / "public" / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()

    receipt = writer.apply(publish_command())

    assert receipt.slug == "example-study"
    assert receipt.sequence == 1
    assert receipt.request_id == "publish-request"
    assert receipt.action is PublicationAction.PUBLISH
    assert SqlitePublicStudyReader(path).get("example-study") == synthetic_snapshot()


def test_list_is_slug_ordered_and_applies_an_exact_topic_filter(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(
        publish_command(
            slug="zebra-study",
            request_id="zebra-request",
            topic_keys=("rag", "retrieval"),
        )
    )
    writer.apply(
        publish_command(
            slug="alpha-study",
            request_id="alpha-request",
            topic_keys=("evaluation",),
        )
    )
    reader = SqlitePublicStudyReader(path)

    assert tuple(item.content.slug for item in reader.list_published()) == (
        "alpha-study",
        "zebra-study",
    )
    assert tuple(item.content.slug for item in reader.list_published("rag")) == (
        "zebra-study",
    )
    assert reader.list_published("rag' OR 1=1 --") == ()


def test_withdrawal_removes_body_and_old_exact_replay_cannot_restore_it(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    publish = publish_command()
    writer.apply(publish)
    writer.apply(withdraw_command(sequence=4))

    replay_receipt = SqlitePublicStudyWriter(path).apply(publish)

    assert replay_receipt == PublicationReceipt(
        slug="example-study",
        sequence=1,
        request_id="publish-request",
        action=PublicationAction.PUBLISH,
    )
    reader = SqlitePublicStudyReader(path)
    with pytest.raises(AppError) as hidden:
        reader.get("example-study")
    assert (hidden.value.code, hidden.value.status_code) == ("not_found", 404)
    assert reader.list_published() == ()
    with sqlite3.connect(path) as connection:
        projection = connection.execute(
            "SELECT sequence, payload, digest FROM public_study_projections WHERE slug = ?",
            ("example-study",),
        ).fetchone()
        history_columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(public_request_history)")
        )
    assert projection == (4, None, None)
    assert history_columns == ("request_id", "fingerprint")


@pytest.mark.parametrize(
    "conflict",
    [
        publish_command(slug="other-study", request_id="shared-request"),
        publish_command(request_id="shared-request", title="변경된 합성 연구"),
    ],
)
def test_request_id_is_global_and_bound_to_one_command(
    tmp_path: Path,
    conflict: PublicationCommand,
) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command(request_id="shared-request"))

    with pytest.raises(AppError) as failure:
        writer.apply(conflict)

    assert failure.value.code == "publishing_command_conflict"
    assert failure.value.status_code == 409
    assert "shared-request" not in str(failure.value)
    assert SqlitePublicStudyReader(path).get("example-study").content.title == "합성 연구"


def test_lower_or_same_conflicting_sequence_cannot_replace_current_projection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command(sequence=5, request_id="current-request"))

    for command in (
        publish_command(sequence=4, request_id="old-request", title="오래된 게시본"),
        publish_command(sequence=5, request_id="parallel-request", title="경합 게시본"),
    ):
        with pytest.raises(AppError) as failure:
            writer.apply(command)
        assert failure.value.status_code == 409

    assert SqlitePublicStudyReader(path).get("example-study").content.title == "합성 연구"


def test_corrupt_entry_is_safe_not_found_and_excluded_without_hiding_valid_entries(
    tmp_path: Path,
) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command())
    writer.apply(publish_command(slug="valid-study", request_id="valid-request"))
    marker = b"private-tampered-payload"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE public_study_projections SET payload = ? WHERE slug = ?",
            (marker, "example-study"),
        )

    reader = SqlitePublicStudyReader(path)
    with pytest.raises(AppError) as failure:
        reader.get("example-study")

    assert (failure.value.code, failure.value.status_code) == ("not_found", 404)
    assert marker.decode() not in str(failure.value)
    assert tuple(item.content.slug for item in reader.list_published()) == ("valid-study",)


def test_valid_but_wrong_slug_payload_is_treated_as_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command())
    wrong = synthetic_snapshot(slug="other-study")

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE public_study_projections SET payload = ?, digest = ? WHERE slug = ?",
            (canonical_bytes(wrong), snapshot_digest(wrong), "example-study"),
        )

    with pytest.raises(AppError) as failure:
        SqlitePublicStudyReader(path).get("example-study")
    assert (failure.value.code, failure.value.status_code) == ("not_found", 404)
    assert SqlitePublicStudyReader(path).list_published() == ()


def test_failed_history_write_rolls_back_projection_replacement(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(publish_command())
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_rollback_request
            BEFORE INSERT ON public_request_history
            WHEN NEW.request_id = 'rollback-request'
            BEGIN
                SELECT RAISE(ABORT, 'synthetic storage failure');
            END
            """
        )

    with pytest.raises(AppError) as failure:
        writer.apply(
            publish_command(
                sequence=2,
                request_id="rollback-request",
                title="롤백되어야 하는 게시본",
            )
        )

    assert (failure.value.code, failure.value.status_code) == (
        "publishing_store_unavailable",
        503,
    )
    assert "synthetic storage failure" not in str(failure.value)
    assert str(path) not in str(failure.value)
    assert SqlitePublicStudyReader(path).get("example-study").content.title == "합성 연구"


def test_missing_read_only_store_is_unavailable_without_creating_a_database(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "missing"
    directory.mkdir()
    path = directory / "studies.sqlite3"

    with pytest.raises(AppError) as failure:
        SqlitePublicStudyReader(path).get("example-study")

    assert (failure.value.code, failure.value.status_code) == (
        "publishing_store_unavailable",
        503,
    )
    assert str(path) not in str(failure.value)
    assert not path.exists()


def test_missing_withdrawn_and_invalid_slug_share_safe_not_found(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    writer.apply(withdraw_command(sequence=3))
    reader = SqlitePublicStudyReader(path)

    for slug in ("example-study", "missing-study", "' OR 1=1 --"):
        with pytest.raises(AppError) as failure:
            reader.get(slug)
        assert (failure.value.code, failure.value.message, failure.value.status_code) == (
            "not_found",
            "The requested resource was not found.",
            404,
        )


def test_lone_surrogate_request_id_is_rejected_safely_before_store_io(tmp_path: Path) -> None:
    path = tmp_path / "missing" / "studies.sqlite3"
    command = publish_command(request_id=f"request-{chr(0xD800)}")

    with pytest.raises(AppError) as failure:
        SqlitePublicStudyWriter(path).apply(command)

    assert (failure.value.code, failure.value.message, failure.value.status_code) == (
        "publishing_command_conflict",
        "The publication command conflicts.",
        409,
    )
    assert not path.exists()


def test_reader_rejects_lone_surrogate_slug_as_safe_not_found(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    SqlitePublicStudyWriter(path).initialize()

    with pytest.raises(AppError) as failure:
        SqlitePublicStudyReader(path).get(f"study-{chr(0xD800)}")

    assert (failure.value.code, failure.value.message, failure.value.status_code) == (
        "not_found",
        "The requested resource was not found.",
        404,
    )


def test_invalid_topic_filter_returns_empty_without_sqlite_binding(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    SqlitePublicStudyWriter(path).initialize()

    assert SqlitePublicStudyReader(path).list_published(f"rag-{chr(0xDFFF)}") == ()


def test_non_bmp_request_id_remains_supported_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "studies.sqlite3"
    writer = SqlitePublicStudyWriter(path)
    writer.initialize()
    command = publish_command(request_id="publish-🧪")

    first = writer.apply(command)
    replay = SqlitePublicStudyWriter(path).apply(command)

    assert first == replay == PublicationReceipt(
        slug="example-study",
        sequence=1,
        request_id="publish-🧪",
        action=PublicationAction.PUBLISH,
    )


@pytest.mark.parametrize("operation", ["detail", "topic-list"])
def test_invalid_reader_input_does_not_mask_a_missing_store(
    tmp_path: Path,
    operation: str,
) -> None:
    path = tmp_path / "missing" / "studies.sqlite3"
    reader = SqlitePublicStudyReader(path)

    with pytest.raises(AppError) as failure:
        if operation == "detail":
            reader.get(f"study-{chr(0xD800)}")
        else:
            reader.list_published(f"rag-{chr(0xDFFF)}")

    assert (failure.value.code, failure.value.message, failure.value.status_code) == (
        "publishing_store_unavailable",
        "The public study store is unavailable.",
        503,
    )
    assert not path.exists()


@pytest.mark.parametrize("operation", ["detail", "topic-list"])
def test_invalid_reader_input_does_not_mask_a_schema_missing_store(
    tmp_path: Path,
    operation: str,
) -> None:
    path = tmp_path / "schema-missing.sqlite3"
    with sqlite3.connect(path):
        pass
    reader = SqlitePublicStudyReader(path)

    with pytest.raises(AppError) as failure:
        if operation == "detail":
            reader.get(f"study-{chr(0xD800)}")
        else:
            reader.list_published(f"rag-{chr(0xDFFF)}")

    assert (failure.value.code, failure.value.message, failure.value.status_code) == (
        "publishing_store_unavailable",
        "The public study store is unavailable.",
        503,
    )
