"""Module CLI control decisions without original settings, DB or native I/O."""

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasRecoveryError


def test_parser_has_no_force_history_or_external_evidence_input(capsys):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import parser

    cli = parser()
    assert all(
        name in cli.format_help() for name in ("preview", "status", "freeze", "recover", "release")
    )
    with pytest.raises(SystemExit) as caught:
        cli.parse_args(["recover", "--proof-json", "private-secret"])
    assert caught.value.code == 2
    output = capsys.readouterr()
    assert "private-secret" not in output.out + output.err


class Service:
    def __init__(self):
        self.calls = []

    async def readback(self, *args):
        self.calls.append("readback")
        raise AliasRecoveryError("rag_alias_commit_unknown")

    async def recover_terminated(self, claim):
        self.calls.append("recover")

    async def release(self, claim):
        self.calls.append("release")


async def test_access_epoch_preflight_only_previews_and_never_recovers_or_readies():
    from datetime import UTC, datetime

    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

    snapshot = AliasOperationSnapshot(
        uuid4(),
        "store",
        "cluster",
        "active",
        uuid4(),
        uuid4(),
        (),
        datetime.now(UTC),
        "legacy_unknown",
    )

    class PreviewOnly(Service):
        async def preview(self, *args):
            self.calls.append("preview")
            return snapshot

    class Probe:
        async def preflight(self, value):
            assert value == snapshot
            return {
                "deployment_observed": True,
                "preflight": "blocked",
                "diagnostic": "historical_control_settlement_unknown",
                "historical_control_settlement": "unknown",
                "termination_proven": False,
                "parity": "not_run",
            }

    service = PreviewOnly()
    args = parser().parse_args(
        [
            "preflight-access-epoch",
            "--operation",
            str(snapshot.operation_id),
            "--actor",
            str(uuid4()),
        ]
    )
    result = await execute(service, args, access_epoch_preflight_port=Probe())
    assert service.calls == ["preview"]
    assert result["preflight"] == "blocked" and not result["termination_proven"]
    assert result["parity"] == "not_run"


async def test_access_epoch_port_cannot_override_identity_or_disclose_untrusted_fields():
    from datetime import UTC, datetime

    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

    snapshot = AliasOperationSnapshot(
        uuid4(),
        "store",
        "cluster",
        "active",
        uuid4(),
        uuid4(),
        (),
        datetime.now(UTC),
        "legacy_unknown",
    )

    class PreviewOnly(Service):
        async def preview(self, *args):
            self.calls.append("preview")
            return snapshot

    class Probe:
        async def preflight(self, value):
            return {
                "deployment_observed": "true",
                "preflight": "ready",
                "termination_proven": True,
                "parity": "run",
                "historical_control_settlement": "settled",
                "route_verification": "verified",
                "diagnostic": "synthetic-secret-marker",
                "private_key": "synthetic-secret-marker",
                "operation_id": "override",
                "snapshot_sha256": "override",
            }

    service = PreviewOnly()
    args = parser().parse_args(
        [
            "preflight-access-epoch",
            "--operation",
            str(snapshot.operation_id),
            "--actor",
            str(uuid4()),
        ]
    )
    result = await execute(service, args, access_epoch_preflight_port=Probe())
    assert (
        result["operation_id"] == str(snapshot.operation_id)
        and result["snapshot_sha256"] == snapshot.sha256
    )
    assert "synthetic-secret-marker" not in json.dumps(result)
    assert (
        result["deployment_observed"] is False
        and result["historical_control_settlement"] == "unknown"
    )
    assert result["route_verification"] == "not_performed"
    assert result["preflight"] == "blocked" and result["termination_proven"] is False
    assert result["parity"] == "not_run" and service.calls == ["preview"]


@pytest.mark.parametrize("local_refusal", [False, True])
async def test_access_epoch_port_exceptions_are_body_free(local_refusal):
    from datetime import UTC, datetime

    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

    snapshot = AliasOperationSnapshot(
        uuid4(),
        "store",
        "cluster",
        "active",
        uuid4(),
        uuid4(),
        (),
        datetime.now(UTC),
        "legacy_unknown",
    )

    class PreviewOnly(Service):
        async def preview(self, *args):
            self.calls.append("preview")
            return snapshot

    class Probe:
        async def preflight(self, value):
            if local_refusal:
                raise LocalRecoveryRefusal("synthetic-secret-marker")
            raise RuntimeError("synthetic-secret-marker")

    service = PreviewOnly()
    args = parser().parse_args(
        [
            "preflight-access-epoch",
            "--operation",
            str(snapshot.operation_id),
            "--actor",
            str(uuid4()),
        ]
    )
    result = await execute(service, args, access_epoch_preflight_port=Probe())
    assert result["diagnostic"] == "access_epoch_observation_failed"
    assert result["preflight"] == "blocked" and result["deployment_observed"] is False
    assert "synthetic-secret-marker" not in json.dumps(result) and service.calls == ["preview"]


@pytest.mark.parametrize("command", ["recover", "release"])
async def test_unknown_readback_has_no_mutation_release_or_parity(command):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser

    service = Service()
    args = parser().parse_args(
        [
            command,
            "--operation",
            str(uuid4()),
            "--actor",
            str(uuid4()),
            "--request",
            str(uuid4()),
        ]
    )
    with pytest.raises(AliasRecoveryError, match="rag_alias_commit_unknown"):
        await execute(service, args)
    assert service.calls == ["readback"]


def test_cli_help_requires_no_settings_or_database(capsys):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import main

    with pytest.raises(SystemExit) as caught:
        main(["--help"])
    assert caught.value.code == 0
    assert "trusted" in capsys.readouterr().out


@pytest.mark.parametrize("command", ["recover", "release"])
async def test_normal_confirmed_winner_is_preserved_without_collector_or_receipt(command):
    from datetime import UTC, datetime

    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser
    from ai_workshop.labs.rag.indexing.alias_recovery_types import (
        AliasOperationSnapshot,
        AliasRecoveryReadback,
        FrozenAliasClaim,
    )

    snapshot = AliasOperationSnapshot(
        uuid4(),
        "store",
        "cluster",
        "active",
        uuid4(),
        uuid4(),
        (),
        datetime.now(UTC),
        "dispatching",
    )
    frozen = FrozenAliasClaim(snapshot, uuid4(), uuid4(), 1)

    class Winner(Service):
        async def readback(self, *args):
            self.calls.append("readback")
            return AliasRecoveryReadback(snapshot, "closed", "confirmed", "frozen", frozen, None)

    service = Winner()
    args = parser().parse_args(
        [
            command,
            "--operation",
            str(snapshot.operation_id),
            "--actor",
            str(frozen.actor_id),
            "--request",
            str(frozen.request_id),
        ]
    )
    result = await execute(service, args)
    assert result["result_code"] == "confirmed"
    assert service.calls == (["readback", "release"] if command == "release" else ["readback"])
    assert result["parity"] == "not_run"
    if command == "release":
        assert result["release_result"] == "released"
        assert result["released_claim"]["request_id"] == str(frozen.request_id)
        assert "current_gate" not in result


@pytest.mark.skipif(sys.platform != "win32", reason="fresh Windows loop boundary")
def test_fresh_windows_main_runs_offline_coroutine_on_selector_loop():
    # Child imports no conftest and never invokes original _run/settings/DB/native I/O.
    script = """
import asyncio
from ai_workshop.labs.rag.indexing import alias_recovery_cli as cli

async def offline_run(args):
    loop = asyncio.get_running_loop()
    return {"entered_run": True, "uses_selector": isinstance(loop, asyncio.SelectorEventLoop)}

cli._run = offline_run
cli.main(["preview", "--operation", "11111111-1111-1111-1111-111111111111",
          "--actor", "22222222-2222-2222-2222-222222222222"])
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[5],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"entered_run": True, "uses_selector": True}


@pytest.mark.parametrize("argv,code", [(["--help"], 0), (["preview"], 2)])
def test_help_and_parser_errors_exit_before_loop_or_runtime_initialization(monkeypatch, argv, code):
    from ai_workshop.labs.rag.indexing import alias_recovery_cli as cli

    def forbidden():
        pytest.fail("help/parser path initialized the runtime loop")

    monkeypatch.setattr(cli, "configure_windows_selector_policy", forbidden)
    with pytest.raises(SystemExit) as caught:
        cli.main(argv)
    assert caught.value.code == code


def sql_cli_case(database=None):
    from types import SimpleNamespace

    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.indexing.alias_recovery import AliasRecoveryService
    from tests.unit.labs.rag.indexing.test_alias_recovery import Database

    db = database or Database()
    settings = Settings(
        _env_file=None,
        secret_key="synthetic-test-secret-value-00000000",
        environment="local",
        rag_index_store_id="rag",
        rag_index_cluster_uuid="cluster",
    )
    return SimpleNamespace(db=db, service=AliasRecoveryService(db, settings))


def sql_cli_args(case, command, request, digest=None, operation=None):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import parser

    args = [
        command,
        "--operation",
        str(operation or case.db.operation.id),
        "--actor",
        str(case.db.actor),
        "--request",
        str(request),
    ]
    if digest is not None:
        args += ["--snapshot-sha256", digest]
    return parser().parse_args(args)


def gate_facts(case):
    from ai_workshop.labs.rag.indexing.alias_models import AliasClusterGateRecord

    gate = case.db.rows[AliasClusterGateRecord, "cluster"]
    return tuple(
        getattr(gate, name)
        for name in (
            "state",
            "request_id",
            "actor_id",
            "operation_id",
            "snapshot_sha256",
            "revision",
        )
    )


async def test_sql_freeze_initial_and_active_replay_report_current_exact_authority():
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute

    case, request = sql_cli_case(), uuid4()
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    args = sql_cli_args(case, "freeze", request, snapshot.sha256)
    result = await execute(case.service, args)
    assert result["state"] == "open"
    assert result["current_gate"] == {
        "state": "frozen",
        "authority_for_request": "matching_frozen_claim",
        "claim": {
            "operation_id": str(snapshot.operation_id),
            "request_id": str(request),
            "actor_id": str(case.db.actor),
            "snapshot_sha256": snapshot.sha256,
            "revision": 1,
        },
    }
    assert "historical_claim" not in result and "receipt" not in result
    before = gate_facts(case)
    assert await execute(case.service, args) == result
    assert gate_facts(case) == before


async def test_sql_freeze_replay_after_release_reports_history_and_no_frozen_barrier():
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute

    case, request = sql_cli_case(), uuid4()
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    freeze_args = sql_cli_args(case, "freeze", request, snapshot.sha256)
    await execute(case.service, freeze_args)
    recovered = await execute(case.service, sql_cli_args(case, "recover", request))
    released = await execute(case.service, sql_cli_args(case, "release", request))
    assert released["release_result"] == "released" and "current_gate" not in released
    assert released["released_claim"] == recovered["historical_claim"]
    before = gate_facts(case)
    result = await execute(case.service, freeze_args)
    assert result["state"] == "closed" and result["result_code"] == "not_dispatched"
    assert result["current_gate"] == {"state": "admitted", "authority_for_request": "not_frozen"}
    assert result["historical_claim"] == recovered["historical_claim"]
    assert result["receipt"] == recovered["receipt"]
    assert result["historical_claim"]["request_id"] == str(request)
    assert (
        "gate_state" not in result and "request_id" not in result and "gate_revision" not in result
    )
    assert gate_facts(case) == before and case.db.operation.state == "closed"


@pytest.mark.parametrize("command", ["freeze", "status", "recover"])
async def test_sql_old_receipt_never_grants_newer_frozen_gate_authority(command):
    from copy import deepcopy

    from ai_workshop.labs.rag.indexing.alias_models import AliasOperationRecord
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute

    case, request = sql_cli_case(), uuid4()
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    await execute(case.service, sql_cli_args(case, "freeze", request, snapshot.sha256))
    recovered = await execute(case.service, sql_cli_args(case, "recover", request))
    await execute(case.service, sql_cli_args(case, "release", request))
    newer = deepcopy(case.db.operation)
    newer.id, newer.state, newer.result_code, newer.closed_at = uuid4(), "open", None, None
    case.db.rows[AliasOperationRecord, newer.id] = newer
    newer_snapshot = await case.service.preview(newer.id, case.db.actor)
    newer_request = uuid4()
    await execute(
        case.service,
        sql_cli_args(case, "freeze", newer_request, newer_snapshot.sha256, operation=newer.id),
    )
    before = gate_facts(case)
    result = await execute(
        case.service,
        sql_cli_args(case, command, request, snapshot.sha256 if command == "freeze" else None),
    )
    assert result["current_gate"] == {"state": "frozen", "authority_for_request": "not_verified"}
    assert result["historical_claim"] == recovered["historical_claim"]
    assert result["receipt"] == recovered["receipt"]
    assert result["historical_claim"]["revision"] < before[-1]
    assert str(newer_request) not in json.dumps(result)
    assert gate_facts(case) == before and newer.state == "open"


async def test_sql_freeze_unknown_readback_stops_without_success_or_followup():
    from sqlalchemy.exc import OperationalError

    from ai_workshop.labs.rag.indexing.alias_models import (
        AliasClusterGateRecord,
        AliasRecoveryReceiptRecord,
    )
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute
    from tests.unit.labs.rag.indexing.test_alias_recovery import Database

    class Fault(Database):
        def __init__(self):
            super().__init__()
            self.readback_attempts = 0

        async def scalar(self, statement):
            if (
                statement.column_descriptions[0]["entity"] is AliasClusterGateRecord
                and statement._for_update_arg is None
            ):
                self.readback_attempts += 1
                raise OperationalError("synthetic", {}, Exception("private-secret"))
            return await super().scalar(statement)

    db = Fault()
    case, request = sql_cli_case(db), uuid4()
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    with pytest.raises(AliasRecoveryError, match="rag_alias_commit_unknown"):
        await execute(case.service, sql_cli_args(case, "freeze", request, snapshot.sha256))
    assert db.readback_attempts == 1
    assert not any(kind is AliasClusterGateRecord for kind, _ in db.rows)
    assert db.operation.state == "open" and case.service.proof_port is None
    assert not any(kind is AliasRecoveryReceiptRecord for kind, _ in db.rows)


class PreflightPort:
    def __init__(self, action=None):
        self.snapshots = []
        self.action = action

    async def preflight(self, snapshot):
        self.snapshots.append(snapshot)
        if self.action:
            self.action()


@pytest.mark.parametrize(
    "phase,expected", [("reserved", "not_required"), ("legacy_unknown", "ready")]
)
async def test_requestless_preflight_reports_no_proof_or_mutation(phase, expected):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser

    case, port = sql_cli_case(), PreflightPort()
    case.db.operation.phase = phase
    args = parser().parse_args(
        ["preflight", "--operation", str(case.db.operation.id), "--actor", str(case.db.actor)]
    )
    result = await execute(case.service, args, port)
    assert result["preflight"] == expected
    assert result["termination_proven"] is False and result["parity"] == "not_run"
    assert len(port.snapshots) == (phase != "reserved")
    assert case.db.operation.state == "open"
    assert not any(
        kind.__name__ in {"AliasClusterGateRecord", "AliasRecoveryReceiptRecord"}
        for kind, _ in case.db.rows
    )


async def test_blocked_preflight_never_acquires_new_gate_and_hides_private_error():
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser

    case = sql_cli_case()
    case.db.operation.phase = "legacy_unknown"

    def blocked():
        raise RuntimeError("synthetic-private-command")

    port = PreflightPort(blocked)
    args = parser().parse_args(
        ["preflight", "--operation", str(case.db.operation.id), "--actor", str(case.db.actor)]
    )
    result = await execute(case.service, args, port)
    assert result["preflight"] == "blocked" and result["termination_proven"] is False
    assert "private" not in json.dumps(result)
    assert not any(kind.__name__ == "AliasClusterGateRecord" for kind, _ in case.db.rows)
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    with pytest.raises(AliasRecoveryError):
        await execute(case.service, sql_cli_args(case, "freeze", uuid4(), snapshot.sha256), port)
    assert not any(kind.__name__ == "AliasClusterGateRecord" for kind, _ in case.db.rows)


@pytest.mark.parametrize(
    "diagnostic,expected",
    [
        ("local_command_failed", "local_command_failed"),
        ("unknown_client_process", "unknown_client_process"),
        ("collector_controller_unverified", "collector_controller_unverified"),
        ("wsl_infrastructure_unverified", "wsl_infrastructure_unverified"),
        ("preflight_clients_blocked", "preflight_clients_blocked"),
        ("unknown_client_process_private-token", "preflight_blocked"),
        ("C:/synthetic-private/command", "preflight_blocked"),
        (None, "preflight_blocked"),
    ],
)
async def test_cli_preflight_preserves_only_positive_safe_diagnostics(diagnostic, expected):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    case = sql_cli_case()
    case.db.operation.phase = "legacy_unknown"

    def refused():
        if diagnostic is None:
            raise RuntimeError("synthetic-private-exception")
        raise LocalRecoveryRefusal(diagnostic)

    port = PreflightPort(refused)
    args = parser().parse_args(
        ["preflight", "--operation", str(case.db.operation.id), "--actor", str(case.db.actor)]
    )
    result = await execute(case.service, args, port)
    assert result["diagnostic"] == expected
    assert result["preflight"] == "blocked" and result["termination_proven"] is False
    assert "private" not in json.dumps(result) and result["parity"] == "not_run"
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    with pytest.raises(LocalRecoveryRefusal) as caught:
        await execute(case.service, sql_cli_args(case, "freeze", uuid4(), snapshot.sha256), port)
    assert caught.value.diagnostic == expected and caught.value.__suppress_context__ is True
    assert not any(
        kind.__name__ in {"AliasClusterGateRecord", "AliasRecoveryReceiptRecord"}
        for kind, _ in case.db.rows
    )


@pytest.mark.parametrize("fault", ["missing", "digest", "readback", "race", "foreign"])
async def test_new_legacy_freeze_failures_leave_operation_open_and_stop_before_acquisition(fault):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute

    case, request = sql_cli_case(), uuid4()
    case.db.operation.phase = "legacy_unknown"
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    port = PreflightPort()
    if fault == "race":
        from datetime import timedelta

        port.action = lambda: setattr(
            case.db.operation, "created_at", case.db.operation.created_at + timedelta(seconds=1)
        )
    if fault == "readback":

        async def unknown(*args):
            raise AliasRecoveryError("rag_alias_commit_unknown")

        case.service.readback = unknown
    if fault == "foreign":
        await case.service.freeze(snapshot.operation_id, case.db.actor, uuid4(), snapshot.sha256)
    with pytest.raises(AliasRecoveryError) as caught:
        await execute(
            case.service,
            sql_cli_args(
                case, "freeze", request, "f" * 64 if fault == "digest" else snapshot.sha256
            ),
            None if fault == "missing" else port,
        )
    assert caught.value.code in {
        "rag_alias_proof_invalid",
        "rag_alias_snapshot_changed",
        "rag_alias_commit_unknown",
        "rag_alias_claim_conflict",
    }
    assert len(port.snapshots) == (fault == "race")
    assert case.db.operation.state == "open"
    if fault == "foreign":
        assert gate_facts(case)[1] != request
    else:
        assert not any(kind.__name__ == "AliasClusterGateRecord" for kind, _ in case.db.rows)


@pytest.mark.parametrize("phase", ["legacy_unknown", "dispatching"])
async def test_new_freeze_preflight_then_exact_cas_and_existing_replay_without_native(phase):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute

    case, port, request = sql_cli_case(), PreflightPort(), uuid4()
    case.db.operation.phase = phase
    snapshot = await case.service.preview(case.db.operation.id, case.db.actor)
    args = sql_cli_args(case, "freeze", request, snapshot.sha256)
    result = await execute(case.service, args, port)
    assert result["current_gate"]["authority_for_request"] == "matching_frozen_claim"
    assert port.snapshots == [snapshot]
    assert await execute(case.service, args) == result
    case.db.operation.state, case.db.operation.result_code = "closed", "confirmed"
    replay = await execute(case.service, args)
    assert replay["result_code"] == "confirmed" and port.snapshots == [snapshot]


def test_main_blocked_preflight_has_nonzero_exit_and_no_proof(monkeypatch, capsys):
    from ai_workshop.labs.rag.indexing import alias_recovery_cli as cli

    async def blocked(args):
        return {"preflight": "blocked", "termination_proven": False, "parity": "not_run"}

    monkeypatch.setattr(cli, "_run", blocked)
    with pytest.raises(SystemExit) as caught:
        cli.main(["preflight", "--operation", str(uuid4()), "--actor", str(uuid4())])
    assert caught.value.code == 1
    assert json.loads(capsys.readouterr().out)["termination_proven"] is False


def synthetic_original_environment(monkeypatch, changes=None, environment=None):
    from pydantic_settings.sources.providers import dotenv

    from ai_workshop.labs.rag.indexing import alias_recovery_cli as cli

    root = Path("C:/synthetic-alias-workspace") if sys.platform == "win32" else Path("/synthetic")
    entries = {
        "AI_WORKSHOP_SECRET_KEY": "synthetic-test-secret-value-00000000",
        "AI_WORKSHOP_ENVIRONMENT": "local",
        "AI_WORKSHOP_DATABASE_URL": "postgresql+psycopg://synthetic:synthetic@127.0.0.1:15432/ai_workshop_local_clean",
        "AI_WORKSHOP_ELASTICSEARCH_URL": "http://127.0.0.1:9200",
        "AI_WORKSHOP_CODEX_RUNNER_REFS": json.dumps(
            {
                "test-runner": {
                    "executable": str(root / "bin/runner.exe"),
                    "request_root": str(root / "requests"),
                    "expected_cli_version": "1.2.3",
                    "executable_sha256": "a" * 64,
                },
            }
        ),
        "AI_WORKSHOP_CODEX_ALLOWED_ADMIN_ORIGINS": '["http://127.0.0.1:5173"]',
        "AI_WORKSHOP_PROVIDER_ENDPOINT_REFS": '{"test-endpoint":"http://127.0.0.1:1234"}',
        "AI_WORKSHOP_PROVIDER_SECRET_REFS": '{"test-credential":"synthetic-private-value"}',
        "AI_WORKSHOP_LEARNING_LIMITS": '{"title_max_chars":77}',
        "AI_WORKSHOP_SESSION_LIFETIME_MINUTES": "37",
        "AI_WORKSHOP_EVALUATION_AUTHORING_MAX_DOCUMENTS": "12",
    } | (changes or {})
    reads = []

    def read_values(path, **kwargs):
        assert path == root / ".env"
        reads.append(path)
        return entries.copy()

    monkeypatch.setattr(cli.os, "environ", environment or {})
    monkeypatch.setattr(Path, "is_symlink", lambda path: False)
    monkeypatch.setattr(Path, "is_file", lambda path: path == root / ".env")
    monkeypatch.setattr(cli, "dotenv_values", read_values, raising=False)
    monkeypatch.setattr(dotenv, "dotenv_values", read_values)
    return root, reads


def test_original_loader_matches_normal_settings_source_for_complex_and_scalar_fields(monkeypatch):
    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings

    root, reads = synthetic_original_environment(monkeypatch)
    expected = Settings(_env_file=root / ".env")
    actual = load_original_settings(root)
    assert actual.model_dump() == expected.model_dump()
    assert actual.codex_runner_refs["test-runner"].expected_cli_version == "1.2.3"
    assert actual.codex_allowed_admin_origins == ("http://127.0.0.1:5173",)
    assert actual.provider_endpoint_refs == {"test-endpoint": "http://127.0.0.1:1234"}
    assert actual.learning_limits.title_max_chars == 77
    assert actual.session_lifetime_minutes == 37
    assert actual.evaluation_authoring_max_documents == 12
    assert reads == [root / ".env", root / ".env"]


@pytest.mark.parametrize("value", ['["synthetic-private-value"]', "not-json-private-value"])
def test_original_loader_invalid_complex_setting_refuses_without_value_leak(monkeypatch, value):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    root, _ = synthetic_original_environment(monkeypatch, {"AI_WORKSHOP_CODEX_RUNNER_REFS": value})
    with pytest.raises(LocalRecoveryRefusal) as caught:
        load_original_settings(root)
    assert caught.value.diagnostic == "original_environment_invalid"
    assert "private-value" not in str(caught.value)


@pytest.mark.parametrize(
    "changes,environment,diagnostic",
    [
        (
            {},
            {"AI_WORKSHOP_SECRET_KEY": "synthetic-private-value"},
            "original_environment_override",
        ),
        (
            {},
            {"HTTP_PROXY": "http://synthetic-private-value:1234"},
            "proxy_environment_unsupported",
        ),
        (
            {"AI_WORKSHOP_ELASTICSEARCH_URL": "http://example.invalid:9200"},
            {},
            "direct_original_endpoint_required",
        ),
        (
            {"AI_WORKSHOP_DATABASE_URL": "postgresql+psycopg://x:x@127.0.0.1:15432/other"},
            {},
            "original_database_required",
        ),
    ],
)
def test_original_loader_preserves_override_proxy_endpoint_and_database_guards(
    monkeypatch,
    changes,
    environment,
    diagnostic,
):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    root, reads = synthetic_original_environment(monkeypatch, changes, environment)
    with pytest.raises(LocalRecoveryRefusal) as caught:
        load_original_settings(root)
    assert caught.value.diagnostic == diagnostic
    assert "private-value" not in str(caught.value)
    if diagnostic == "original_environment_override":
        assert reads == []


@pytest.mark.parametrize("environment", ["test", "production"])
def test_original_loader_preserves_local_only_guard(monkeypatch, environment):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings

    root, _ = synthetic_original_environment(
        monkeypatch,
        {
            "AI_WORKSHOP_ENVIRONMENT": environment,
            "AI_WORKSHOP_PUBLISHING_DELIVERY_MODE": "manual",
        },
    )
    with pytest.raises(AliasRecoveryError, match="rag_alias_local_required"):
        load_original_settings(root)


@pytest.mark.parametrize("symlink", [False, True])
def test_original_loader_refuses_missing_or_symlink_file_before_read(monkeypatch, symlink):
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    root, reads = synthetic_original_environment(monkeypatch)
    monkeypatch.setattr(Path, "is_symlink", lambda path: symlink)
    monkeypatch.setattr(Path, "is_file", lambda path: False)
    with pytest.raises(LocalRecoveryRefusal) as caught:
        load_original_settings(root)
    assert caught.value.diagnostic == "original_environment_required"
    assert reads == []
