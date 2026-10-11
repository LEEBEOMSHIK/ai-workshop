"""Local operator module CLI. Each command is an explicit, exact operation.

After commit uncertainty use status with the SAME request. Recovery, definitive
readback, release and ordinary scoped parity are separate operator steps.
"""

import argparse
import asyncio
import json
import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Never, Protocol
from urllib.parse import urlsplit
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService
from ai_workshop.labs.rag.indexing.alias_recovery_local import (
    LocalRecoveryRefusal,
    LocalTerminationCollector,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    HISTORY_KIND,
    MODULE,
    OriginalWindowsBackend,
    safe_preflight_diagnostic,
    validate_endpoint,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import (
    AliasOperationSnapshot,
    AliasRecoveryError,
    AliasRecoveryReadback,
    AliasRecoveryReceipt,
    FrozenAliasClaim,
)
from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy
from ai_workshop.shared.db import create_engine, create_session_factory


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, '{"error_code":"rag_alias_cli_arguments_invalid"}\n')


def _sha(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("invalid digest")
    return value


def parser() -> argparse.ArgumentParser:
    cli = SafeArgumentParser(
        prog=f"python -m {MODULE}",
        description="Exact alias recovery by a trusted local operator using original .env.",
        epilog=(
            f"History source: {HISTORY_KIND}. Assumes no endpoint overrides, copied cluster, "
            "privileged record edits or manual/automation host/guest writers during maintenance. "
            "Stop writers and supervisors first. Unknowns preserve open/frozen. "
            "After unknown commit use status with the SAME operation/actor/request; "
            "do not restart, release or run parity to resolve it. "
            "Parity is a separate ordinary run_once."
        ),
    )
    commands = cli.add_subparsers(dest="command", required=True, parser_class=SafeArgumentParser)
    for name in (
        "preview",
        "preflight",
        "preflight-access-epoch",
        "status",
        "freeze",
        "recover",
        "release",
    ):
        command = commands.add_parser(name)
        command.add_argument("--operation", type=UUID, required=True)
        command.add_argument("--actor", type=UUID, required=True)
        if name not in {"preview", "preflight", "preflight-access-epoch"}:
            command.add_argument("--request", type=UUID, required=True)
        if name == "freeze":
            command.add_argument("--snapshot-sha256", type=_sha, required=True)
    return cli


class RecoveryFacade(Protocol):
    async def preview(self, operation_id: UUID, actor_id: UUID) -> AliasOperationSnapshot: ...
    async def freeze(
        self,
        operation_id: UUID,
        actor_id: UUID,
        request_id: UUID,
        snapshot_sha256: str,
    ) -> FrozenAliasClaim: ...
    async def readback(
        self,
        operation_id: UUID,
        actor_id: UUID,
        request_id: UUID,
    ) -> AliasRecoveryReadback: ...
    async def recover_not_dispatched(self, claim: FrozenAliasClaim) -> AliasRecoveryReceipt: ...
    async def recover_terminated(self, claim: FrozenAliasClaim) -> AliasRecoveryReceipt: ...
    async def release(self, claim: FrozenAliasClaim) -> None: ...


class PreflightPort(Protocol):
    async def preflight(self, snapshot: AliasOperationSnapshot) -> None: ...


class AccessEpochPreflightPort(Protocol):
    async def preflight(self, snapshot: AliasOperationSnapshot) -> dict[str, object]: ...


async def _preflight(snapshot: AliasOperationSnapshot, port: PreflightPort | None) -> None:
    if port is None:
        raise LocalRecoveryRefusal("preflight_capability_required")
    try:
        await port.preflight(snapshot)
    except LocalRecoveryRefusal as exc:
        diagnostic = safe_preflight_diagnostic(exc.diagnostic, "preflight_blocked")
        raise LocalRecoveryRefusal(diagnostic) from None
    except Exception:
        raise LocalRecoveryRefusal("preflight_blocked") from None


def _snapshot(snapshot: AliasOperationSnapshot) -> dict[str, object]:
    return {
        "operation_id": str(snapshot.operation_id),
        "snapshot_sha256": snapshot.sha256,
        "phase": snapshot.phase,
        "target_count": len(snapshot.targets),
        "indexing_profile_id": str(snapshot.indexing_profile_id),
        "document_processing_profile_id": str(snapshot.document_processing_profile_id),
    }


def _status(status: AliasRecoveryReadback) -> dict[str, object]:
    gate: dict[str, object] = {
        "state": status.gate_state,
        "authority_for_request": "not_frozen"
        if status.gate_state != "frozen"
        else "matching_frozen_claim"
        if status.claim is not None and status.receipt is None
        else "not_verified",
    }
    result = _snapshot(status.snapshot) | {
        "state": status.state,
        "result_code": status.result_code,
        "current_gate": gate,
        "parity": "not_run",
    }
    if status.claim is not None:
        if status.receipt is not None or status.gate_state != "frozen":
            # Receipt or admitted-gate claims do not establish current frozen ownership.
            result["historical_claim"] = _claim(status.claim)
        else:
            gate["claim"] = _claim(status.claim)
    if status.receipt is not None:
        receipt = status.receipt
        result["receipt"] = {
            "operation_id": str(receipt.operation_id),
            "request_id": str(receipt.request_id),
            "actor_id": str(receipt.actor_id),
            "snapshot_sha256": receipt.snapshot_sha256,
            "gate_revision": receipt.gate_revision,
            "result_code": receipt.result_code,
            "proof_sha256": receipt.proof_sha256,
        }
    return result


def _claim(claim: FrozenAliasClaim) -> dict[str, object]:
    return {
        "operation_id": str(claim.snapshot.operation_id),
        "request_id": str(claim.request_id),
        "actor_id": str(claim.actor_id),
        "snapshot_sha256": claim.snapshot.sha256,
        "revision": claim.revision,
    }


def _released(status: AliasRecoveryReadback, claim: FrozenAliasClaim) -> dict[str, object]:
    result = _status(status)
    # Release confirms an exact action, not a subsequent live gate observation.
    result.pop("current_gate")
    return result | {"release_result": "released", "released_claim": _claim(claim)}


def _exact(status: AliasRecoveryReadback, args: argparse.Namespace) -> FrozenAliasClaim:
    claim = status.claim
    if (
        claim is None
        or claim.request_id != args.request
        or claim.actor_id != args.actor
        or claim.snapshot.operation_id != args.operation
        or claim.snapshot != status.snapshot
    ):
        raise AliasRecoveryError("rag_alias_claim_conflict")
    return claim


async def execute(
    service: RecoveryFacade,
    args: argparse.Namespace,
    preflight_port: PreflightPort | None = None,
    *,
    access_epoch_preflight_port: AccessEpochPreflightPort | None = None,
) -> dict[str, object]:
    if args.command == "preflight-access-epoch":
        snapshot = await service.preview(args.operation, args.actor)
        if access_epoch_preflight_port is None:
            return _snapshot(snapshot) | {
                "preflight": "blocked",
                "diagnostic": "access_epoch_preflight_required",
                "termination_proven": False,
                "parity": "not_run",
            }
        try:
            observation = await access_epoch_preflight_port.preflight(snapshot)
        except LocalRecoveryRefusal as exc:
            observation = {
                "diagnostic": safe_preflight_diagnostic(
                    exc.diagnostic, "access_epoch_observation_failed"
                )
            }
        except Exception:
            observation = {"diagnostic": "access_epoch_observation_failed"}
        # Snapshot/authority never comes from a native payload or a future port.
        diagnostic = observation.get("diagnostic")
        if type(diagnostic) is not str or diagnostic not in {
            "access_epoch_binding_mismatch",
            "historical_control_settlement_unknown",
            "access_epoch_observation_failed",
        }:
            diagnostic = safe_preflight_diagnostic(diagnostic, "access_epoch_observation_failed")
        return _snapshot(snapshot) | {
            "deployment_observed": observation.get("deployment_observed") is True,
            "diagnostic": diagnostic,
            "historical_control_settlement": "unknown",
            "route_verification": "not_performed",
            "preflight": "blocked",
            "termination_proven": False,
            "parity": "not_run",
        }
    if args.command == "preview":
        return _snapshot(await service.preview(args.operation, args.actor))
    if args.command == "preflight":
        snapshot = await service.preview(args.operation, args.actor)
        result = _snapshot(snapshot) | {"termination_proven": False, "parity": "not_run"}
        if snapshot.phase == "reserved":
            return result | {"preflight": "not_required"}
        try:
            await _preflight(snapshot, preflight_port)
        except LocalRecoveryRefusal as exc:
            return result | {
                "preflight": "blocked",
                "diagnostic": exc.diagnostic,
                "error_code": exc.code,
            }
        return result | {"preflight": "ready"}
    if args.command == "freeze":
        snapshot = await service.preview(args.operation, args.actor)
        if snapshot.sha256 != args.snapshot_sha256:
            raise AliasRecoveryError("rag_alias_snapshot_changed")
        before = await service.readback(args.operation, args.actor, args.request)
        if before.snapshot != snapshot:
            raise AliasRecoveryError("rag_alias_snapshot_changed")
        if before.claim is not None:
            _exact(before, args)
        elif before.gate_state == "frozen" or before.receipt is not None:
            raise AliasRecoveryError("rag_alias_claim_conflict")
        elif before.state == "open" and snapshot.phase in {"legacy_unknown", "dispatching"}:
            # Preview/readback transactions have ended. Freeze still performs the definitive CAS.
            await _preflight(snapshot, preflight_port)
        claim = await service.freeze(
            args.operation,
            args.actor,
            args.request,
            args.snapshot_sha256,
        )
        status = await service.readback(args.operation, args.actor, args.request)
        if status.claim != claim:
            raise AliasRecoveryError("rag_alias_claim_conflict")
        return _status(status)
    status = await service.readback(args.operation, args.actor, args.request)
    if args.command == "status":
        return _status(status)
    claim = _exact(status, args)
    if status.state == "closed" and status.result_code == "confirmed" and status.receipt is None:
        if args.command == "release":
            await service.release(claim)
            return _released(status, claim)
        if args.command == "recover":
            return _status(status)
    if args.command == "release":
        receipt = status.receipt
        if (
            receipt is None
            or status.state != "closed"
            or receipt.request_id != claim.request_id
            or receipt.actor_id != claim.actor_id
            or receipt.operation_id != claim.snapshot.operation_id
            or receipt.snapshot_sha256 != claim.snapshot.sha256
            or receipt.gate_revision != claim.revision
        ):
            raise AliasRecoveryError("rag_alias_operation_open")
        await service.release(claim)
        return _released(status, claim)
    if args.command != "recover":
        raise AliasRecoveryError("rag_alias_claim_conflict")
    if status.receipt is None:
        if status.snapshot.phase == "reserved":
            await service.recover_not_dispatched(claim)
        else:
            await service.recover_terminated(claim)
        # Definitive receipt readback. Uncertain response stops this command;
        # no automatic release, restart or recursive recovery/parity.
        status = await service.readback(args.operation, args.actor, args.request)
    receipt = status.receipt
    if (
        receipt is None
        or receipt.request_id != args.request
        or receipt.actor_id != args.actor
        or receipt.operation_id != args.operation
        or status.state != "closed"
    ):
        raise AliasRecoveryError("rag_alias_commit_unknown")
    return _status(status)


def repository_root() -> Path:
    # Source module is intentionally tied to this approved workspace layout.
    root = Path(__file__).resolve().parents[6]
    if not (root / "AGENTS.md").is_file() or not (root / "backend/src/ai_workshop").is_dir():
        raise LocalRecoveryRefusal("original_workspace_required")
    return root


def load_original_settings(root: Path) -> Settings:
    try:
        if any(key.upper().startswith("AI_WORKSHOP_") for key in os.environ):
            raise LocalRecoveryRefusal("original_environment_override")
        path = root / ".env"
        if path.is_symlink() or not path.is_file():
            raise LocalRecoveryRefusal("original_environment_required")
        # Use the application source pipeline, including complex-field JSON decoding.
        settings = Settings(_env_file=path)  # type: ignore[call-arg]
        if settings.environment != "local":
            raise AliasRecoveryError("rag_alias_local_required")
        validate_endpoint(settings.elasticsearch_url, os.environ)
        database = urlsplit(settings.database_url)
        if (
            database.scheme != "postgresql+psycopg"
            or database.hostname != "127.0.0.1"
            or database.port != 15432
            or database.path != "/ai_workshop_local_clean"
            or database.query
            or database.fragment
        ):
            raise LocalRecoveryRefusal("original_database_required")
        return settings
    except AliasRecoveryError:
        raise
    except Exception:
        raise LocalRecoveryRefusal("original_environment_invalid") from None


async def _run(args: argparse.Namespace) -> dict[str, object]:
    root = repository_root()
    settings = load_original_settings(root)
    engine = create_engine(settings)
    try:
        service = AliasRecoveryService(create_session_factory(engine), settings)

        async def authority(claim: FrozenAliasClaim) -> AliasRecoveryReadback:
            return await service.readback(
                claim.snapshot.operation_id, claim.actor_id, claim.request_id
            )

        backend = OriginalWindowsBackend(settings, root)
        if args.command not in {"preflight", "preflight-access-epoch"}:
            service.proof_port = LocalTerminationCollector(backend, authority)
        if args.command == "preflight-access-epoch":
            from ai_workshop.labs.rag.indexing.access_epoch_native import (
                OriginalAccessEpochPreflight,
            )

            return await execute(
                service, args, access_epoch_preflight_port=OriginalAccessEpochPreflight(settings)
            )
        return await execute(service, args, backend)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> None:
    args = parser().parse_args(argv)
    try:
        configure_windows_selector_policy()
        output = asyncio.run(_run(args))
    except LocalRecoveryRefusal as exc:
        output = {"error_code": exc.code, "diagnostic": exc.diagnostic, "parity": "not_run"}
        if args.command in {"preflight", "preflight-access-epoch"}:
            output |= {"preflight": "blocked", "termination_proven": False}
        print(json.dumps(output, sort_keys=True))
        raise SystemExit(1) from None
    except AliasRecoveryError as exc:
        output = {"error_code": exc.code, "parity": "not_run"}
        if args.command in {"preflight", "preflight-access-epoch"}:
            output |= {"preflight": "blocked", "termination_proven": False}
        print(json.dumps(output, sort_keys=True))
        raise SystemExit(1) from None
    except Exception:
        output = {"error_code": "rag_alias_cli_failed", "parity": "not_run"}
        if args.command in {"preflight", "preflight-access-epoch"}:
            output |= {"preflight": "blocked", "termination_proven": False}
        print(json.dumps(output, sort_keys=True))
        raise SystemExit(1) from None
    print(json.dumps(output, sort_keys=True))
    if output.get("preflight") == "blocked":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
