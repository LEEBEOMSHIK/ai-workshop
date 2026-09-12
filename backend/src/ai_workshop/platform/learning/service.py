from __future__ import annotations

import base64
import binascii
import hmac
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ai_workshop.config import LearningLimits
from ai_workshop.platform.learning.domain import LearningRecord
from ai_workshop.platform.learning.references import (
    ReferenceResolver,
    ReferenceStatus,
    ReferenceView,
)
from ai_workshop.platform.learning.repository import (
    LearningCursor,
    LearningListFilters,
    LearningRepository,
    LearningSummary,
)
from ai_workshop.platform.learning.schemas import (
    LearningDraft,
    ReferenceKey,
    load_learning_topics,
)
from ai_workshop.shared.errors import AppError


async def _no_op_commit() -> None:
    return None


@dataclass(frozen=True, slots=True)
class LearningRecordView:
    id: UUID
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    draft: LearningDraft
    reference_views: tuple[ReferenceView, ...]
    dataset_reference_view: ReferenceView | None
    unavailable_reference_count: int


@dataclass(frozen=True, slots=True)
class LearningListView:
    items: tuple[LearningSummary, ...]
    next_cursor: str | None


class LearningCursorCodec:
    def __init__(self, secret_key: str, *, max_length: int) -> None:
        if not secret_key or max_length < 1:
            raise ValueError("A cursor codec requires a secret and positive maximum length.")
        self._signing_key = hmac.digest(
            secret_key.encode("utf-8"), b"ai-workshop:learning-cursor:v1", "sha256"
        )
        self._max_length = max_length

    def encode(
        self,
        actor_id: UUID,
        filters: LearningListFilters,
        cursor: LearningCursor,
    ) -> str:
        payload = json.dumps(
            {
                "actor": str(actor_id),
                "filters": _filter_payload(filters),
                "position": {
                    "record_id": str(cursor.record_id),
                    "updated_at": cursor.updated_at.isoformat(),
                },
                "version": 1,
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        signature = hmac.digest(self._signing_key, payload, "sha256")
        encoded = f"{_base64_encode(payload)}.{_base64_encode(signature)}"
        if len(encoded) > self._max_length:
            raise AppError(
                "learning_invalid_input", "The learning request is invalid.", 422
            )
        return encoded

    def decode(
        self,
        value: str,
        actor_id: UUID,
        filters: LearningListFilters,
    ) -> LearningCursor:
        if not value or len(value) > self._max_length:
            raise _invalid_input()
        try:
            encoded_payload, encoded_signature = value.split(".", maxsplit=1)
            payload = _base64_decode(encoded_payload)
            signature = _base64_decode(encoded_signature)
            expected_signature = hmac.digest(self._signing_key, payload, "sha256")
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("invalid signature")
            decoded = json.loads(payload)
            if not isinstance(decoded, dict):
                raise ValueError("invalid payload")
            if decoded.get("version") != 1:
                raise ValueError("invalid version")
            if decoded.get("actor") != str(actor_id):
                raise ValueError("invalid actor")
            if decoded.get("filters") != _filter_payload(filters):
                raise ValueError("invalid filters")
            position = decoded["position"]
            if not isinstance(position, dict):
                raise ValueError("invalid position")
            updated_at = datetime.fromisoformat(position["updated_at"])
            if updated_at.tzinfo is None:
                raise ValueError("cursor timestamp must include a timezone")
            record_id = UUID(position["record_id"])
        except (
            ValueError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            binascii.Error,
        ) as exc:
            raise _invalid_input() from exc
        return LearningCursor(updated_at=updated_at, record_id=record_id)


def _base64_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.b64decode(value + padding, altchars=b"-_", validate=True)


def _filter_payload(filters: LearningListFilters) -> dict[str, object]:
    return {
        "archived": filters.archived,
        "kind": filters.kind.value if filters.kind is not None else None,
        "topic_key": filters.topic_key,
    }


class LearningService:
    def __init__(
        self,
        repository: LearningRepository,
        resolver: ReferenceResolver,
        limits: LearningLimits,
        cursor_codec: LearningCursorCodec,
        *,
        commit: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.repository = repository
        self.resolver = resolver
        self.limits = limits
        self.cursor_codec = cursor_codec
        self.commit = commit or _no_op_commit

    @property
    def default_page_limit(self) -> int:
        return self.limits.page_default

    async def create(self, actor_id: UUID, draft: LearningDraft) -> LearningRecordView:
        self._validate_draft(draft)
        resolved_references = await self._require_available_references(actor_id, draft)
        record = await self.repository.create(
            LearningRecord.create(owner_id=actor_id, draft=draft)
        )
        await self.commit()
        return self._available_write_view(record, resolved_references)

    async def detail(
        self,
        actor_id: UUID,
        record_id: UUID,
        revision: int | None = None,
    ) -> LearningRecordView:
        if revision is None:
            record = await self.repository.get_owned(record_id, actor_id)
        else:
            if revision < 1:
                raise _invalid_input()
            record = await self.repository.get_revision_owned(record_id, revision, actor_id)
        if record is None:
            raise _not_found()
        return await self._to_view(actor_id, record)

    async def update(
        self,
        actor_id: UUID,
        record_id: UUID,
        expected_revision: int,
        draft: LearningDraft,
    ) -> LearningRecordView:
        record = await self.repository.get_owned(record_id, actor_id)
        if record is None:
            raise _not_found()
        revised = record.revise(draft, expected_revision=expected_revision)
        self._validate_draft(draft)
        resolved_references = await self._require_available_references(actor_id, draft)
        saved = await self.repository.save_revision(revised, expected_revision)
        await self.commit()
        return self._available_write_view(saved, resolved_references)

    async def archive(
        self, actor_id: UUID, record_id: UUID, expected_revision: int
    ) -> LearningRecordView:
        record = await self.repository.get_owned(record_id, actor_id)
        if record is None:
            raise _not_found()
        archived = record.archive(expected_revision=expected_revision)
        response = await self._to_view(actor_id, archived)
        await self.repository.save_revision(archived, expected_revision)
        await self.commit()
        return response

    async def restore(
        self, actor_id: UUID, record_id: UUID, expected_revision: int
    ) -> LearningRecordView:
        record = await self.repository.get_owned(record_id, actor_id)
        if record is None:
            raise _not_found()
        restored = record.restore(expected_revision=expected_revision)
        response = await self._to_view(actor_id, restored)
        await self.repository.save_revision(restored, expected_revision)
        await self.commit()
        return response

    async def list_for(
        self,
        actor_id: UUID,
        filters: LearningListFilters,
        cursor: str | None,
        limit: int,
    ) -> LearningListView:
        if limit < 1 or limit > self.limits.page_max:
            raise _invalid_input()
        if filters.topic_key is not None:
            topics = {topic.key for topic in load_learning_topics()}
            if filters.topic_key not in topics:
                raise _invalid_input()
        decoded_cursor = None
        if cursor:
            if len(cursor) > self.limits.cursor_max_chars:
                raise _invalid_input()
            decoded_cursor = self.cursor_codec.decode(cursor, actor_id, filters)
        page = await self.repository.list_owned(actor_id, filters, decoded_cursor, limit)
        next_cursor = (
            self.cursor_codec.encode(actor_id, filters, page.next_cursor)
            if page.next_cursor is not None
            else None
        )
        return LearningListView(items=page.items, next_cursor=next_cursor)

    def _validate_draft(self, draft: LearningDraft) -> None:
        if len(draft.title) > self.limits.title_max_chars:
            raise _invalid_input()
        if len(draft.body) > self.limits.body_max_chars:
            raise _invalid_input()
        reference_count = len(draft.references)
        if draft.experiment is not None and draft.experiment.dataset_snapshot is not None:
            reference_count += 1
        if reference_count > self.limits.max_references:
            raise _invalid_input()
        payload = draft.model_dump(mode="json")
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        if len(serialized) > self.limits.aggregate_draft_max_bytes:
            raise _invalid_input()
        self._validate_nested(payload, path=())

    def _validate_nested(self, value: object, *, path: tuple[str, ...]) -> None:
        if isinstance(value, str):
            if path not in {("title",), ("body",)} and (
                len(value) > self.limits.max_text_field_chars
            ):
                raise _invalid_input()
            return
        if isinstance(value, Mapping):
            for key, item in value.items():
                self._validate_nested(item, path=(*path, str(key)))
            return
        if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
            if len(value) > self.limits.max_collection_items:
                raise _invalid_input()
            for item in value:
                self._validate_nested(item, path=path)

    async def _require_available_references(
        self, actor_id: UUID, draft: LearningDraft
    ) -> tuple[ReferenceView, ...]:
        resolved: list[ReferenceView] = []
        for key in _all_reference_keys(draft):
            view = await self.resolver.resolve(actor_id, key)
            if view.status is not ReferenceStatus.AVAILABLE:
                raise AppError(
                    "learning_reference_unavailable",
                    "A learning reference is unavailable.",
                    422,
                )
            resolved.append(view)
        return tuple(resolved)

    def _available_write_view(
        self,
        record: LearningRecord,
        resolved_references: tuple[ReferenceView, ...],
    ) -> LearningRecordView:
        top_level_count = len(record.draft.references)
        dataset_view = (
            resolved_references[top_level_count]
            if len(resolved_references) > top_level_count
            else None
        )
        return LearningRecordView(
            id=record.id,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            archived_at=record.archived_at,
            draft=record.draft,
            reference_views=resolved_references[:top_level_count],
            dataset_reference_view=dataset_view,
            unavailable_reference_count=0,
        )

    async def _to_view(
        self, actor_id: UUID, record: LearningRecord
    ) -> LearningRecordView:
        reference_views: list[ReferenceView] = []
        visible_references = []
        unavailable_count = 0
        for key in record.draft.references:
            view = await self.resolver.resolve(actor_id, key)
            reference_views.append(view)
            if view.status is ReferenceStatus.AVAILABLE:
                visible_references.append(key)
            else:
                unavailable_count += 1

        dataset_view = None
        experiment = record.draft.experiment
        if experiment is not None and experiment.dataset_snapshot is not None:
            dataset_view = await self.resolver.resolve(
                actor_id, experiment.dataset_snapshot
            )
            if dataset_view.status is ReferenceStatus.UNAVAILABLE:
                unavailable_count += 1
                experiment = experiment.model_copy(update={"dataset_snapshot": None})

        sanitized_draft = record.draft.model_copy(
            update={
                "references": tuple(visible_references),
                "experiment": experiment,
            }
        )
        return LearningRecordView(
            id=record.id,
            revision=record.revision,
            created_at=record.created_at,
            updated_at=record.updated_at,
            archived_at=record.archived_at,
            draft=sanitized_draft,
            reference_views=tuple(reference_views),
            dataset_reference_view=dataset_view,
            unavailable_reference_count=unavailable_count,
        )


def _all_reference_keys(draft: LearningDraft) -> tuple[ReferenceKey, ...]:
    keys = list(draft.references)
    if draft.experiment is not None and draft.experiment.dataset_snapshot is not None:
        keys.append(draft.experiment.dataset_snapshot)
    return tuple(keys)


def _invalid_input() -> AppError:
    return AppError("learning_invalid_input", "The learning request is invalid.", 422)


def _not_found() -> AppError:
    return AppError("not_found", "The requested resource was not found.", 404)
