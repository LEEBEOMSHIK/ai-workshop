"""Restore only against server-owned execution context, never the JSON envelope."""

from collections.abc import Sequence
from uuid import UUID

from .numeric_proof_schemas import ClaimView, NumericValidationBindingView, payload_from_views
from .numeric_validation_repository import SqlAlchemyNumericValidationRepository, invalid


async def verify_numeric_views(
    repository: SqlAlchemyNumericValidationRepository,
    *,
    actor_id: UUID,
    execution_id: UUID | None,
    status: str,
    answer: str | None,
    claims: Sequence[ClaimView],
    binding: NumericValidationBindingView | None,
    configuration_version_id: UUID | None = None,
    generation_profile_id: UUID | None = None,
) -> None:
    has_fields = binding is not None or any(claim.calculations is not None for claim in claims)
    if execution_id is None:
        if has_fields:
            raise invalid()
        return
    try:
        expected = await repository.expected_context_for_execution(
            actor_id=actor_id, execution_id=execution_id
        )
    except Exception:
        raise invalid() from None
    if expected is None:
        if has_fields:
            raise invalid()
        return
    if (
        binding is None
        or configuration_version_id is not None
        and expected.configuration_version_id != configuration_version_id
        or generation_profile_id is not None
        and expected.generation_profile_id != generation_profile_id
    ):
        raise invalid()
    try:
        payload = payload_from_views(status=status, answer=answer, claims=claims, binding=binding)
    except ValueError:
        raise invalid() from None
    try:
        await repository.verify_binding(binding.domain(), payload, expected=expected)
    except Exception:
        raise invalid() from None
