"""One scoped parity pass, exclusively inside an admitted registered child."""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Sequence
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.service_bootstrap_context import (
    VerifiedLaunchCapability,
    current_verified_launch,
)
from ai_workshop.infrastructure.local.service_launcher import SERVICE_MODULES
from ai_workshop.infrastructure.local.windows_process import process_identity
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_runtime import (
    require_launch_role,
    verify_original_runtime,
)
from ai_workshop.labs.rag.indexing.recovery import (
    RagAliasParityResult,
    SqlAlchemyRagAliasParityReconciler,
)
from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy


class _Parser:
    def parse_args(self, argv: Sequence[str] | None = None) -> argparse.Namespace:
        try:
            arguments = list(sys.argv[1:] if argv is None else argv)
            if len(arguments) != 2 or arguments[0] != "--profile":
                raise ValueError
            profile_id = UUID(arguments[1])
            if str(profile_id) != arguments[1]:
                raise ValueError
            return argparse.Namespace(profile=profile_id)
        except Exception:
            raise ValueError("access_epoch_parity_arguments") from None


def parser() -> _Parser:
    return _Parser()


def _birth(settings: Settings, profile_id: UUID) -> VerifiedLaunchCapability:
    capability = current_verified_launch()
    if (
        type(profile_id) is not UUID
        or type(capability) is not VerifiedLaunchCapability
        or capability.service != "parity"
        or capability.module != SERVICE_MODULES["parity"]
        or capability.role != "writer"
        or type(capability.pid) is not int
        or capability.pid != os.getpid()
        or type(capability.ordinal) is not int
        or capability.ordinal < 1
        or type(capability.bound_ids) is not tuple
        or capability.bound_ids != (profile_id,)
        or any(type(value) is not UUID for value in capability.bound_ids)
        or settings.environment != "local"
        or settings.elasticsearch_access_epoch_id is None
        or capability.epoch_id != settings.elasticsearch_access_epoch_id
        or capability.ordinal != settings.elasticsearch_access_epoch
        or settings.elasticsearch_role != "writer"
    ):
        raise ValueError("access_epoch_parity_denied")
    require_launch_role(settings, writer=True)
    created, _image = process_identity(capability.pid)
    if capability.creation_time != created:
        raise ValueError("access_epoch_parity_denied")
    return capability


def _summary(profile_id: UUID | None, error_code: str | None) -> dict[str, object]:
    return {
        "profile_id": str(profile_id) if type(profile_id) is UUID else None,
        "claimed": 0,
        "reconciled": 0,
        "failed": 0,
        "error_code": error_code,
    }


async def run(profile_id: UUID) -> dict[str, object]:
    output = _summary(profile_id, "access_epoch_parity_denied")
    try:
        path = PROJECT_ROOT / ".env"
        if path.is_symlink() or not path.is_file():
            raise ValueError("access_epoch_parity_denied")
        settings = Settings(_env_file=path)  # type: ignore[call-arg]
        capability = _birth(settings, profile_id)
        await verify_original_runtime(settings, writer=True)
        if _birth(settings, profile_id) is not capability:
            raise ValueError("access_epoch_parity_denied")
    except Exception:
        return output
    output["error_code"] = "access_epoch_parity_failed"
    try:
        # The existing reconciler's journal locks/requires the admitted gate before
        # every alias operation. This child never releases a gate or writes a receipt.
        result = await SqlAlchemyRagAliasParityReconciler(settings).run_once(profile_id=profile_id)
        if (
            type(result) is not RagAliasParityResult
            or any(
                type(value) is not int or value not in (0, 1)
                for value in (result.claimed, result.reconciled, result.failed)
            )
            or result.reconciled + result.failed != result.claimed
            or type(result.failures) is not tuple
            or len(result.failures) > 1
        ):
            return output
        output.update(claimed=result.claimed, reconciled=result.reconciled, failed=result.failed)
        if (result.claimed, result.reconciled, result.failed) == (1, 1, 0) and not result.failures:
            output["error_code"] = None
        return output
    except Exception:
        return output


def main(argv: Sequence[str] | None = None) -> None:
    try:
        args = parser().parse_args(argv)
    except ValueError:
        print(json.dumps(_summary(None, "access_epoch_parity_arguments"), sort_keys=True))
        raise SystemExit(2) from None
    try:
        configure_windows_selector_policy()
        output = asyncio.run(run(args.profile))
    except Exception:
        output = _summary(args.profile, "access_epoch_parity_failed")
    print(json.dumps(output, sort_keys=True))
    if output["error_code"] is not None:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
