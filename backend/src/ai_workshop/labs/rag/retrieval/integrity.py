from ai_workshop.labs.rag.retrieval.domain import (
    ResolvedSearchScope,
    SelectedDocumentIdentity,
)
from ai_workshop.shared.errors import AppError


def require_authorized_identities(
    required: tuple[SelectedDocumentIdentity, ...],
    current: ResolvedSearchScope,
) -> None:
    if not set(required).issubset(current.authorized_documents):
        raise AppError(
            "conversation_scope_changed",
            "The search scope changed. Select sources again.",
            409,
        )
