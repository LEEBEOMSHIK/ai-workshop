from math import inf, nan
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.platform.learning.domain import (
    ExperimentStatus,
    LearningRecord,
    RecordKind,
)
from ai_workshop.platform.learning.schemas import (
    ExperimentFields,
    ExperimentMetric,
    LearningDraft,
    ReferenceKey,
    TroubleshootingFields,
)
from ai_workshop.shared.errors import AppError


def note_draft(*, title: str = "Chunking notes") -> LearningDraft:
    return LearningDraft(title=title, body="Compare structure boundaries.", kind="note")


def test_note_needs_no_experiment_fields() -> None:
    owner_id = uuid4()
    draft = note_draft()

    record = LearningRecord.create(owner_id=owner_id, draft=draft)

    assert record.owner_id == owner_id
    assert record.draft is draft
    assert record.revision == 1
    assert record.draft.experiment is None
    assert record.archived_at is None
    assert record.created_at.tzinfo is not None
    assert record.updated_at == record.created_at


def test_experiment_can_be_saved_as_a_partial_draft() -> None:
    draft = LearningDraft(
        title="Retrieval comparison",
        body="Work in progress.",
        kind="experiment",
        experiment=ExperimentFields(),
    )

    record = LearningRecord.create(owner_id=uuid4(), draft=draft)

    assert record.draft.kind is RecordKind.EXPERIMENT
    assert record.draft.experiment is not None
    assert record.draft.experiment.status is ExperimentStatus.PLANNED
    assert record.draft.experiment.purpose is None
    assert record.draft.experiment.hypothesis is None


def test_note_conversion_returns_a_new_revision_without_mutating_the_old_record() -> None:
    original = LearningRecord.create(
        owner_id=uuid4(),
        draft=LearningDraft(
            title="Retrieval notes",
            body="Keep this source material.",
            kind="note",
            topic_keys=("rag",),
            references=(ReferenceKey(kind="service", target="rag-search"),),
        ),
    )
    converted_draft = LearningDraft(
        title=original.draft.title,
        body=original.draft.body,
        kind="experiment",
        topic_keys=original.draft.topic_keys,
        references=original.draft.references,
        experiment=ExperimentFields(purpose="Turn the notes into a comparison."),
    )

    converted = original.revise(converted_draft, expected_revision=1)

    assert converted is not original
    assert converted.revision == 2
    assert converted.draft.kind is RecordKind.EXPERIMENT
    assert converted.draft.references == original.draft.references
    assert original.revision == 1
    assert original.draft.kind is RecordKind.NOTE


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "Invalid", "body": "Unknown kind.", "kind": "report"},
        {
            "title": "Invalid",
            "body": "A note cannot carry experiment fields.",
            "kind": "note",
            "experiment": {},
        },
        {"title": "Invalid", "body": "Unknown input.", "kind": "note", "payload": {}},
    ],
)
def test_learning_draft_rejects_invalid_states(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LearningDraft.model_validate(payload)


def test_experiment_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        ExperimentFields.model_validate({"status": "succeeded"})


def test_stale_revision_is_a_conflict() -> None:
    record = LearningRecord.create(owner_id=uuid4(), draft=note_draft())

    with pytest.raises(AppError) as raised:
        record.revise(note_draft(title="Updated"), expected_revision=0)

    assert raised.value.code == "learning_revision_conflict"
    assert raised.value.status_code == 409
    assert record.revision == 1


def test_archive_and_restore_reject_invalid_lifecycle_transitions() -> None:
    active = LearningRecord.create(owner_id=uuid4(), draft=note_draft())

    with pytest.raises(AppError) as active_restore:
        active.restore(expected_revision=1)
    assert active_restore.value.code == "learning_record_not_archived"
    assert active_restore.value.status_code == 409

    archived = active.archive(expected_revision=1)
    with pytest.raises(AppError) as repeated_archive:
        archived.archive(expected_revision=2)
    assert repeated_archive.value.code == "learning_record_already_archived"
    assert repeated_archive.value.status_code == 409


def test_archived_record_is_readable_but_not_editable_until_restored() -> None:
    active = LearningRecord.create(owner_id=uuid4(), draft=note_draft())

    archived = active.archive(expected_revision=1)

    assert archived.revision == 2
    assert archived.archived_at is not None
    assert archived.draft.body == "Compare structure boundaries."
    assert active.archived_at is None
    with pytest.raises(AppError) as raised:
        archived.revise(note_draft(title="Blocked edit"), expected_revision=2)
    assert raised.value.code == "learning_record_archived"
    assert raised.value.status_code == 409

    restored = archived.restore(expected_revision=2)
    edited = restored.revise(note_draft(title="Allowed edit"), expected_revision=3)

    assert restored.revision == 3
    assert restored.archived_at is None
    assert edited.revision == 4
    assert edited.draft.title == "Allowed edit"


@pytest.mark.parametrize("value", [nan, inf, -inf, "0.75", True])
def test_metric_values_must_be_typed_finite_numbers(value: object) -> None:
    with pytest.raises(ValidationError):
        ExperimentMetric(name="citation accuracy", value=value, unit="ratio")


def test_experiment_fields_have_typed_metrics_and_troubleshooting() -> None:
    dataset = ReferenceKey(kind="dataset.snapshot", target="eval-set", version="v1")
    experiment = ExperimentFields(
        purpose="Compare retrieval methods.",
        hypothesis="Hybrid retrieval improves recall.",
        dataset_snapshot=dataset,
        configurations=("bm25", "hybrid-rrf"),
        environment="local-cpu",
        procedure="Run the fixed query set.",
        observations="Hybrid found one more relevant passage.",
        metrics=(ExperimentMetric(name="recall", value=0.75, unit="ratio"),),
        limitations="Small synthetic evaluation set.",
        conclusion="Collect more examples before deciding.",
        next_steps=("Expand the evaluation set.",),
        status="completed",
        troubleshooting=TroubleshootingFields(
            symptom="One query returned no passages.",
            reproduction="Run query q-7.",
            facts=("The document is indexed.",),
            hypotheses=("The token differs.",),
            confirmed_cause="The query used a stale identifier.",
            change="Use the current identifier.",
            verification="Query q-7 returns passages.",
            unresolved=("Check older snapshots.",),
        ),
    )

    assert experiment.dataset_snapshot == dataset
    assert experiment.metrics[0].value == 0.75
    assert experiment.troubleshooting is not None
    assert experiment.troubleshooting.facts == ("The document is indexed.",)


def test_topic_keys_are_validated_against_the_study_topic_registry() -> None:
    draft = LearningDraft(
        title="Study topics",
        body="RAG and fine-tuning are study topics.",
        kind="note",
        topic_keys=("rag", "fine-tuning"),
        domain_labels=("insurance",),
    )

    assert draft.topic_keys == ("rag", "fine-tuning")
    assert draft.domain_labels == ("insurance",)

    with pytest.raises(ValidationError, match="unknown learning topic"):
        LearningDraft(
            title="Unknown topic",
            body="This must not imply service availability.",
            kind="note",
            topic_keys=("public-rag-lab",),
        )


def test_reference_keys_forbid_unrestricted_fields() -> None:
    with pytest.raises(ValidationError):
        ReferenceKey.model_validate(
            {
                "kind": "service",
                "target": "rag-search",
                "version": None,
                "payload": {"model": "hardcoded-model"},
            }
        )


@pytest.mark.parametrize("field", ["title", "body"])
def test_learning_draft_requires_non_blank_title_and_body(field: str) -> None:
    payload = {"title": "Title", "body": "Body", "kind": "note"}
    payload[field] = "   "

    with pytest.raises(ValidationError, match=f"{field} must not be blank"):
        LearningDraft.model_validate(payload)
