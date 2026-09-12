"""Session-scoped approval transitions after policy/actor/space/asset/document locks.

The caller owns the transaction and authorization checks. It must hold an exclusive
asset lock (including first approval), then this helper locks the current state.
This allows request resolution to use the same mutation in its own transaction.
"""

import json
from datetime import datetime
from hashlib import sha256
from typing import Literal
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from .codex_approval_models import EvidenceApprovalEventRecord, EvidenceApprovalStateRecord
from .codex_authorization import CodexAuthorizationError, CodexAuthorizationErrorCode


class ApprovalConflict(CodexAuthorizationError):
    def __init__(self) -> None:
        super().__init__(CodexAuthorizationErrorCode.EVIDENCE_APPROVAL_CONFLICT)


def next_generation(current: int, *, expected_generation: int) -> int:
    if (
        type(current) is not int
        or type(expected_generation) is not int
        or current < 0
        or current != expected_generation
    ):
        raise ApprovalConflict()
    return current + 1


async def mutate_evidence_approval(
    session: AsyncSession,
    *,
    actor_id: UUID,
    revision_id: UUID,
    provider: str,
    action: Literal["approve", "revoke"],
    content_sha256: str | None,
    classification: str | None,
    expected_generation: int,
    request_id: UUID,
    occurred_at: datetime,
) -> int:
    """Return original generation on replay, never reapply a historical transition."""
    # Strict values also apply to internal callers. Receipt identity is actor + UUID.
    next_generation(expected_generation, expected_generation=expected_generation)
    if not isinstance(request_id, UUID):
        raise ApprovalConflict()
    digest = sha256(
        json.dumps(
            {
                "actor_id": str(actor_id),
                "revision_id": str(revision_id),
                "provider": provider,
                "action": action,
                "content_sha256": content_sha256,
                "classification": classification,
                "expected_generation": expected_generation,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    # Serialize an actor's exact request identity even across different revisions.
    # Every mutation holds only one asset and one receipt lock; no later asset locks.
    lock_key = int.from_bytes(
        sha256(f"{actor_id}:{request_id}".encode()).digest()[:8], "big", signed=True
    )
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    receipt = await session.scalar(
        select(EvidenceApprovalEventRecord).where(
            EvidenceApprovalEventRecord.actor_id == actor_id,
            EvidenceApprovalEventRecord.request_id == request_id,
        )
    )
    if receipt is not None:
        if receipt.request_digest != digest:
            raise ApprovalConflict()
        return receipt.generation
    state = await session.scalar(
        select(EvidenceApprovalStateRecord)
        .where(
            EvidenceApprovalStateRecord.revision_id == revision_id,
            EvidenceApprovalStateRecord.provider == provider,
        )
        .with_for_update()
    )
    generation = next_generation(
        state.generation if state else 0, expected_generation=expected_generation
    )
    if action == "approve":
        if classification not in ("public", "synthetic") or content_sha256 is None:
            raise ApprovalConflict()
        if state is not None and state.status == "approved":
            raise ApprovalConflict()
        if state is None:
            state = EvidenceApprovalStateRecord(revision_id=revision_id, provider=provider)
            session.add(state)
        state.classification = classification
        state.content_sha256 = content_sha256
        state.approved_at = occurred_at
        state.revoked_at = None
        state.status = "approved"
    elif action == "revoke":
        if state is None or state.status != "approved":
            raise ApprovalConflict()
        state.revoked_at = occurred_at
        state.status = "revoked"
    else:
        raise ApprovalConflict()
    state.generation = generation
    session.add(
        EvidenceApprovalEventRecord(
            revision_id=revision_id,
            provider=provider,
            generation=generation,
            action=action,
            actor_id=actor_id,
            occurred_at=occurred_at,
            classification=state.classification,
            content_sha256=state.content_sha256,
            request_id=request_id,
            request_digest=digest,
        )
    )
    await session.flush()
    return generation
