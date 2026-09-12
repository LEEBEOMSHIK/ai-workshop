import hashlib
import json
from collections.abc import Sequence
from uuid import UUID

from ai_workshop.labs.rag.retrieval.domain import SelectedDocumentIdentity
from ai_workshop.shared.errors import AppError

RAW_SELECTION_LIMIT_MULTIPLIER = 10


def reject_explicit_empty_document_ids(value: object) -> object:
    if value is None or value == []:
        raise ValueError("An explicit document selection must not be empty.")
    return value


def normalize_document_ids(
    document_ids: Sequence[UUID] | None,
    *,
    max_count: int,
) -> tuple[UUID, ...] | None:
    if document_ids is None:
        return None
    if len(document_ids) > max_count * RAW_SELECTION_LIMIT_MULTIPLIER:
        raise AppError(
            "document_selection_limit_exceeded",
            "The document selection request is too large.",
            422,
        )
    normalized = tuple(sorted(set(document_ids), key=str))
    if not normalized:
        raise AppError(
            "document_selection_empty",
            "An explicit document selection must not be empty.",
            422,
        )
    if len(normalized) > max_count:
        raise AppError(
            "document_selection_limit_exceeded",
            f"At most {max_count} documents may be selected.",
            422,
        )
    return normalized


def selected_scope_fingerprint(
    identities: Sequence[SelectedDocumentIdentity],
) -> str:
    payload = [
        {
            "asset_version_id": str(identity.asset_version_id),
            "document_id": str(identity.document_id),
            "index_build_id": str(identity.index_build_id),
            "projection_id": str(identity.projection_id),
        }
        for identity in sorted(identities, key=lambda item: str(item.document_id))
    ]
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
