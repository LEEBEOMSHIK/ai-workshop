from dataclasses import FrozenInstanceError

import pytest

from ai_workshop.platform.publishing.domain import (
    PublicationAction,
    PublicationCommand,
    PublicationDraft,
)
from ai_workshop.platform.publishing.package import StudyContent, StudySnapshot, snapshot_digest
from ai_workshop.shared.errors import AppError


def synthetic_content(**changes: object) -> StudyContent:
    values: dict[str, object] = {
        "slug": "example-study",
        "title": "합성 연구",
        "summary": "공개 계약을 검증하는 합성 요약",
        "topic_keys": ("rag",),
        "body": "private-submitted-value",
        "verification": "게시와 철회 순서를 확인함",
        "limitations": "실제 자료와 외부 서비스를 사용하지 않음",
    }
    values.update(changes)
    return StudyContent.model_validate(values)


def synthetic_snapshot(*, revision: int = 1, content: StudyContent | None = None) -> StudySnapshot:
    return StudySnapshot(revision=revision, content=content or synthetic_content())


def approved_draft() -> PublicationDraft:
    draft = PublicationDraft(snapshot=synthetic_snapshot())
    return draft.approve(
        expected_revision=1,
        expected_digest=snapshot_digest(draft.snapshot),
    )


def test_revise_increments_revision_clears_approval_and_preserves_sequence() -> None:
    approved, _command = approved_draft().publish(request_id="publish-one")

    revised = approved.revise(
        synthetic_content(title="수정된 합성 연구"),
        expected_revision=1,
    )

    assert revised.snapshot.revision == 2
    assert revised.snapshot.content.title == "수정된 합성 연구"
    assert revised.approved_digest is None
    assert revised.sequence == 1
    assert approved.snapshot.revision == 1
    assert approved.approved_digest is not None
    with pytest.raises(AppError) as failure:
        revised.publish(request_id="publish-unapproved-edit")
    assert failure.value.status_code == 409


@pytest.mark.parametrize("expected_revision", [0, 2, True, 1.0, "1"])
def test_revise_rejects_stale_or_non_strict_revision(expected_revision: object) -> None:
    draft = PublicationDraft(snapshot=synthetic_snapshot())

    with pytest.raises(AppError) as failure:
        draft.revise(synthetic_content(title="수정 시도"), expected_revision=expected_revision)  # type: ignore[arg-type]

    assert failure.value.status_code == 409
    assert draft.snapshot.revision == 1


def test_revise_forbids_public_slug_rename() -> None:
    draft = PublicationDraft(snapshot=synthetic_snapshot())

    with pytest.raises(AppError) as failure:
        draft.revise(synthetic_content(slug="renamed-study"), expected_revision=1)

    assert failure.value.status_code == 409


@pytest.mark.parametrize("expected_revision", [0, True, 1.0, "1"])
def test_approve_rejects_stale_or_non_strict_revision(expected_revision: object) -> None:
    draft = PublicationDraft(snapshot=synthetic_snapshot())

    with pytest.raises(AppError) as failure:
        draft.approve(
            expected_revision=expected_revision,  # type: ignore[arg-type]
            expected_digest=snapshot_digest(draft.snapshot),
        )

    assert failure.value.status_code == 409


def test_approve_rejects_digest_for_different_content() -> None:
    draft = PublicationDraft(snapshot=synthetic_snapshot())
    other = synthetic_snapshot(content=synthetic_content(body="다른 합성 본문"))

    with pytest.raises(AppError) as failure:
        draft.approve(expected_revision=1, expected_digest=snapshot_digest(other))

    assert failure.value.status_code == 409
    assert draft.approved_digest is None


def test_explicit_repeat_publish_emits_new_sequence_with_exact_approved_payload() -> None:
    approved = approved_draft()

    after_first, first = approved.publish(request_id="publish-one")
    after_second, second = after_first.publish(request_id="publish-two")

    assert first.action is PublicationAction.PUBLISH
    assert first.sequence == 1
    assert first.slug == approved.snapshot.content.slug
    assert first.snapshot is approved.snapshot
    assert first.digest == snapshot_digest(approved.snapshot)
    assert second.sequence == 2
    assert second.request_id == "publish-two"
    assert after_second.sequence == 2
    assert after_second.approved_digest == approved.approved_digest


def test_withdraw_has_no_payload_and_requires_reapproval_before_republish() -> None:
    published, _publish = approved_draft().publish(request_id="publish-one")

    withdrawn, command = published.withdraw(request_id="withdraw-one")

    assert command.action is PublicationAction.WITHDRAW
    assert command.sequence == 2
    assert command.snapshot is None
    assert command.digest is None
    assert withdrawn.approved_digest is None
    with pytest.raises(AppError) as failure:
        withdrawn.publish(request_id="publish-without-reapproval")
    assert failure.value.status_code == 409

    reapproved = withdrawn.approve(
        expected_revision=1,
        expected_digest=snapshot_digest(withdrawn.snapshot),
    )
    _republished, republish = reapproved.publish(request_id="publish-after-reapproval")
    assert republish.sequence == 3


def test_domain_dataclasses_are_frozen_and_hide_snapshot_content_from_repr() -> None:
    draft = approved_draft()
    _next_draft, command = draft.publish(request_id="publish-one")

    with pytest.raises(FrozenInstanceError):
        draft.sequence = 9
    with pytest.raises(FrozenInstanceError):
        command.digest = None
    assert "private-submitted-value" not in repr(draft)
    assert "private-submitted-value" not in repr(command)


@pytest.mark.parametrize(
    "changes",
    [
        {"sequence": 0},
        {"sequence": -1},
        {"sequence": True},
        {"request_id": "  \r\n "},
        {"slug": "../private"},
        {"action": "publish"},
        {"snapshot": None},
        {"digest": None},
        {"slug": "other-study"},
        {"digest": "0" * 64},
    ],
)
def test_publish_command_constructor_rejects_malformed_state(changes: dict[str, object]) -> None:
    snapshot = synthetic_snapshot()
    values: dict[str, object] = {
        "slug": "example-study",
        "sequence": 1,
        "request_id": "publish-one",
        "action": PublicationAction.PUBLISH,
        "snapshot": snapshot,
        "digest": snapshot_digest(snapshot),
    }
    values.update(changes)

    with pytest.raises(AppError) as failure:
        PublicationCommand(**values)  # type: ignore[arg-type]

    assert failure.value.code == "publishing_command_invalid"
    assert failure.value.status_code == 422


@pytest.mark.parametrize(
    "changes",
    [
        {"snapshot": synthetic_snapshot()},
        {"digest": "0" * 64},
    ],
)
def test_withdraw_command_constructor_rejects_any_payload(changes: dict[str, object]) -> None:
    values: dict[str, object] = {
        "slug": "example-study",
        "sequence": 1,
        "request_id": "withdraw-one",
        "action": PublicationAction.WITHDRAW,
        "snapshot": None,
        "digest": None,
    }
    values.update(changes)

    with pytest.raises(AppError) as failure:
        PublicationCommand(**values)  # type: ignore[arg-type]

    assert failure.value.code == "publishing_command_invalid"
    assert failure.value.status_code == 422


@pytest.mark.parametrize(
    "values",
    [
        {"sequence": -1},
        {"sequence": True},
        {"approved_digest": "0" * 64},
    ],
)
def test_draft_constructor_rejects_invalid_persisted_state(values: dict[str, object]) -> None:
    with pytest.raises(AppError) as failure:
        PublicationDraft(snapshot=synthetic_snapshot(), **values)  # type: ignore[arg-type]

    assert failure.value.code == "publishing_draft_invalid"
    assert failure.value.status_code == 422
