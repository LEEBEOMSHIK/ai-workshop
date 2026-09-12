import pytest

from ai_workshop.platform.publishing.domain import (
    PublicationAction,
    PublicationCommand,
    PublicationDraft,
)
from ai_workshop.platform.publishing.package import StudyContent, StudySnapshot, snapshot_digest
from ai_workshop.platform.publishing.projection import PublicStudyProjection
from ai_workshop.shared.errors import AppError


def synthetic_snapshot(*, title: str = "합성 연구", slug: str = "example-study") -> StudySnapshot:
    return StudySnapshot(
        revision=1,
        content=StudyContent(
            slug=slug,
            title=title,
            summary="공개 계약을 검증하는 합성 요약",
            topic_keys=("rag",),
            body="공개 계약을 검증하는 합성 본문",
            verification="게시와 철회 순서를 확인함",
            limitations="실제 자료와 외부 서비스를 사용하지 않음",
        ),
    )


def publish_command(
    *,
    sequence: int = 1,
    request_id: str = "publish-request",
    snapshot: StudySnapshot | None = None,
) -> PublicationCommand:
    selected = snapshot or synthetic_snapshot()
    return PublicationCommand(
        slug=selected.content.slug,
        sequence=sequence,
        request_id=request_id,
        action=PublicationAction.PUBLISH,
        snapshot=selected,
        digest=snapshot_digest(selected),
    )


def test_withdrawal_prevents_late_publish_resurrection() -> None:
    snapshot = synthetic_snapshot()
    draft = PublicationDraft(snapshot=snapshot)
    draft = draft.approve(
        expected_revision=1,
        expected_digest=snapshot_digest(draft.snapshot),
    )
    draft, publish = draft.publish(request_id="publish-request")
    _draft, withdraw = draft.withdraw(request_id="withdraw-request")
    public = PublicStudyProjection(slug="example-study").apply(withdraw)

    with pytest.raises(AppError) as failure:
        public.apply(publish)
    assert failure.value.status_code == 409

    with pytest.raises(AppError) as hidden:
        public.read()
    assert hidden.value.code == "not_found"


def test_same_exact_command_is_idempotent_but_same_sequence_conflicts_are_rejected() -> None:
    first = publish_command()
    public = PublicStudyProjection(slug="example-study").apply(first)

    assert public.apply(first) is public

    conflicting_request = publish_command(request_id="different-request")
    with pytest.raises(AppError) as request_conflict:
        public.apply(conflicting_request)
    assert request_conflict.value.status_code == 409

    withdraw = PublicationCommand(
        slug="example-study",
        sequence=1,
        request_id="publish-request",
        action=PublicationAction.WITHDRAW,
        snapshot=None,
        digest=None,
    )
    with pytest.raises(AppError) as action_conflict:
        public.apply(withdraw)
    assert action_conflict.value.status_code == 409

    changed_content = publish_command(snapshot=synthetic_snapshot(title="다른 합성 연구"))
    with pytest.raises(AppError) as content_conflict:
        public.apply(changed_content)
    assert content_conflict.value.status_code == 409


def test_newer_sequence_allows_gaps_but_rejects_last_request_id_reuse() -> None:
    public = PublicStudyProjection(slug="example-study").apply(publish_command())
    gap_withdraw = PublicationCommand(
        slug="example-study",
        sequence=5,
        request_id="withdraw-request",
        action=PublicationAction.WITHDRAW,
        snapshot=None,
        digest=None,
    )

    withdrawn = public.apply(gap_withdraw)

    assert withdrawn.sequence == 5
    assert withdrawn.snapshot is None
    reused = publish_command(sequence=6, request_id="withdraw-request")
    with pytest.raises(AppError) as failure:
        withdrawn.apply(reused)
    assert failure.value.status_code == 409


def test_apply_rejects_wrong_slug_and_command_tampered_after_construction() -> None:
    public = PublicStudyProjection(slug="example-study")
    other = publish_command(snapshot=synthetic_snapshot(slug="other-study"))

    with pytest.raises(AppError) as wrong_slug:
        public.apply(other)
    assert wrong_slug.value.status_code == 409

    tampered = publish_command()
    object.__setattr__(tampered, "digest", "0" * 64)
    with pytest.raises(AppError) as malformed:
        public.apply(tampered)
    assert malformed.value.status_code == 409


def test_private_revision_does_not_mutate_previously_returned_public_snapshot() -> None:
    draft = PublicationDraft(snapshot=synthetic_snapshot())
    draft = draft.approve(
        expected_revision=1,
        expected_digest=snapshot_digest(draft.snapshot),
    )
    published_draft, command = draft.publish(request_id="publish-request")
    public = PublicStudyProjection(slug="example-study").apply(command)

    revised = published_draft.revise(
        synthetic_snapshot(title="비공개 수정본").content,
        expected_revision=1,
    )

    assert revised.snapshot.content.title == "비공개 수정본"
    assert public.read().content.title == "합성 연구"


def test_read_revalidates_snapshot_against_last_approved_digest() -> None:
    public = PublicStudyProjection(slug="example-study").apply(publish_command())
    assert public.snapshot is not None
    object.__setattr__(
        public.snapshot,
        "content",
        synthetic_snapshot(title="승인되지 않은 변조").content,
    )

    with pytest.raises(AppError) as failure:
        public.read()

    assert failure.value.code == "not_found"
    assert failure.value.status_code == 404


@pytest.mark.parametrize(
    "values",
    [
        {"slug": "../private"},
        {"sequence": True},
        {"sequence": 1},
        {"sequence": 0, "last_command": publish_command(), "snapshot": synthetic_snapshot()},
        {"sequence": 1, "last_command": publish_command(), "snapshot": None},
    ],
)
def test_projection_constructor_rejects_inconsistent_state(values: dict[str, object]) -> None:
    defaults: dict[str, object] = {"slug": "example-study"}
    defaults.update(values)

    with pytest.raises(AppError) as failure:
        PublicStudyProjection(**defaults)  # type: ignore[arg-type]

    assert failure.value.code == "publishing_projection_invalid"
    assert failure.value.status_code == 422
