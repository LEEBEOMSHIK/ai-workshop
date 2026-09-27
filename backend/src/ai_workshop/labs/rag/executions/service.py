import base64
import hashlib
import json
from dataclasses import replace
from datetime import UTC
from math import ceil
from statistics import median
from uuid import UUID

from pydantic import ValidationError

from ai_workshop.labs.rag.conversations.access import source_identities
from ai_workshop.labs.rag.conversations.service import ConversationAccessPort
from ai_workshop.labs.rag.executions.domain import STAGES, StageObservation
from ai_workshop.labs.rag.executions.read_repository import MonitoringEntry, MonitoringRepository
from ai_workshop.labs.rag.executions.schemas import (
    ExecutionDetailResponse,
    ExecutionSearchRequest,
    ExecutionSearchResponse,
    ExecutionSummary,
    MonitoringGeneration,
)
from ai_workshop.labs.rag.search.schemas import EvidenceAnswerResponse
from ai_workshop.shared.errors import AppError


def missing() -> AppError:
    return AppError("not_found", "The execution is unavailable.", 404)


def stages(entry: MonitoringEntry) -> list[StageObservation]:
    data = entry.execution.stages if entry.execution else {}
    return [
        StageObservation.model_validate(data[name])
        if name in data
        else StageObservation(stage=name, state="unrecorded")
        for name in STAGES
    ]


def summary(entry: MonitoringEntry) -> ExecutionSummary:
    record, turn = entry.execution, entry.turn
    response = turn.response or {}
    generation = response.get("generation")
    answer = generation.get("status") if isinstance(generation, dict) else None
    selected = next((s.selection for s in stages(entry) if s.selection), None)
    config = response.get("configuration_version")
    raw_config = config.get("version_id") if isinstance(config, dict) else None
    return ExecutionSummary(
        id=record.id if record else turn.id,
        record_kind="execution" if record else "legacy",
        conversation_id=entry.conversation_id,
        turn_id=turn.id,
        domain_id=entry.domain_id,
        domain_slug=entry.domain_slug,
        query=turn.query,
        created_at=turn.created_at,
        status=turn.status,
        answer_status=str(answer) if answer else None,
        failed_stage=next((s.stage for s in stages(entry) if s.state == "failed"), None),
        error_code=turn.error_code,
        duration_ms=max(0, (record.ended_at - record.created_at).total_seconds() * 1000)
        if record and record.ended_at
        else None,
        document_count=len({d[0] for d in source_identities(response)}),
        observation_complete=bool(record and record.complete),
        configuration_version_id=selected.configuration_version_id
        if selected
        else UUID(str(raw_config))
        if raw_config
        else None,
    )


class ExecutionReadService:
    def __init__(self, repository: MonitoringRepository, access: ConversationAccessPort) -> None:
        self.repository, self.access = repository, access

    async def _current_visible(self, actor_id: UUID, turn_id: UUID) -> MonitoringEntry | None:
        # Re-read each member of the dependency closure. No authorization cache survives
        # an enumeration or a different detail request.
        stack: list[tuple[UUID, bool]] = [(turn_id, False)]
        checked: dict[UUID, MonitoringEntry] = {}
        visiting: set[UUID] = set()
        conversation_id: UUID | None = None
        while stack:
            id, expanded = stack.pop()
            if expanded:
                fresh = await self.repository.find(actor_id, id, legacy=True)
                old = checked[id]
                if (
                    fresh is None
                    or fresh.turn.updated_at != old.turn.updated_at
                    or fresh.turn.dependencies != old.turn.dependencies
                    or (fresh.execution.stages if fresh.execution else {})
                    != (old.execution.stages if old.execution else {})
                ):
                    return None
                visiting.discard(id)
                checked[id] = fresh
                continue
            if id in visiting:
                return None
            if id in checked:
                continue
            entry = await self.repository.find(actor_id, id, legacy=True)
            if entry is None or entry.owner_id != actor_id:
                return None
            if conversation_id is None:
                conversation_id = entry.conversation_id
            if entry.conversation_id != conversation_id:
                return None
            payload: dict[str, object] = {
                "response": entry.turn.response,
                "observations": entry.execution.stages if entry.execution else {},
            }
            if not await self.access.visible(actor_id, replace(entry.turn, response=payload)):
                return None
            checked[id] = entry
            visiting.add(id)
            stack.append((id, True))
            stack.extend((parent, False) for parent in reversed(entry.turn.dependencies))
        return checked.get(turn_id)

    async def _authorized(self, actor_id: UUID) -> list[MonitoringEntry]:
        ids = [entry.turn.id async for entry in self.repository.entries(actor_id)]
        result = []
        for id in ids:
            fresh = await self._current_visible(actor_id, id)
            if fresh is not None:
                result.append(fresh)
        return result

    async def search(
        self, actor_id: UUID, request: ExecutionSearchRequest
    ) -> ExecutionSearchResponse:
        rows = [summary(e) for e in await self._authorized(actor_id)]
        rows = [r for r in rows if self._matches(r, request)]
        rows.sort(key=self._key, reverse=True)
        durations = sorted(r.duration_ms for r in rows if r.duration_ms is not None)
        digest = hashlib.sha256(
            (str(actor_id) + request.model_dump_json(exclude={"cursor", "limit"})).encode()
        ).hexdigest()
        eligible = rows
        if request.cursor:
            try:
                cursor = json.loads(base64.urlsafe_b64decode(request.cursor))
                if cursor["filter"] != digest or not isinstance(cursor["after"], list):
                    raise ValueError()
                after = tuple(cursor["after"])
                if len(after) != 3 or not all(isinstance(value, str) for value in after):
                    raise ValueError()
                eligible = [r for r in rows if self._key(r) < after]
            except (ValueError, KeyError, TypeError) as exc:
                raise AppError("invalid_cursor", "Reload the execution list.", 422) from exc
        page = eligible[: request.limit]
        cursor_out = (
            base64.urlsafe_b64encode(
                json.dumps({"filter": digest, "after": self._key(page[-1])}).encode()
            ).decode()
            if len(eligible) > request.limit
            else None
        )
        return ExecutionSearchResponse(
            items=page,
            next_cursor=cursor_out,
            total=len(rows),
            failed_count=sum(r.status == "failed" for r in rows),
            insufficient_count=sum(r.answer_status == "insufficient_evidence" for r in rows),
            duration_count=len(durations),
            duration_missing=len(rows) - len(durations),
            median_ms=median(durations) if durations else None,
            p95_ms=durations[ceil(len(durations) * 0.95) - 1] if durations else None,
        )

    @staticmethod
    def _key(row: ExecutionSummary) -> tuple[str, str, str]:
        return row.created_at.astimezone(UTC).isoformat(), row.record_kind, str(row.id)

    @staticmethod
    def _matches(row: ExecutionSummary, request: ExecutionSearchRequest) -> bool:
        for name in (
            "domain_id",
            "kind",
            "status",
            "answer_status",
            "failed_stage",
            "configuration_version_id",
        ):
            expected = getattr(request, name)
            if expected is not None and getattr(row, name) != expected:
                return False
        return (
            request.query.casefold() in row.query.casefold()
            and (request.started_after is None or row.created_at >= request.started_after)
            and (request.started_before is None or row.created_at <= request.started_before)
        )

    async def detail(self, actor_id: UUID, execution_id: UUID) -> ExecutionDetailResponse:
        return await self._detail(actor_id, execution_id, legacy=False)

    async def legacy(self, actor_id: UUID, turn_id: UUID) -> ExecutionDetailResponse:
        return await self._detail(actor_id, turn_id, legacy=True)

    async def _detail(self, actor_id: UUID, id: UUID, *, legacy: bool) -> ExecutionDetailResponse:
        target = await self.repository.find(actor_id, id, legacy=legacy)
        fresh = await self._current_visible(actor_id, target.turn.id) if target else None
        if fresh is None:
            raise missing()
        response = fresh.turn.response or {}
        raw_evidence = response.get("grounding_evidence", [])
        evidence = (
            [EvidenceAnswerResponse.model_validate(e) for e in raw_evidence]
            if isinstance(raw_evidence, list)
            else []
        )
        raw_generation = response.get("generation")
        try:
            generation = (
                MonitoringGeneration.model_validate(raw_generation) if raw_generation else None
            )
        except ValidationError:
            generation = None
        return ExecutionDetailResponse(
            **summary(fresh).model_dump(),
            stages=stages(fresh),
            generation=generation,
            evidence=evidence,
            usage=await self.repository.usage(actor_id, fresh.execution.id)
            if fresh.execution
            else [],
        )
