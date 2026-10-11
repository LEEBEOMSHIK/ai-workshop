"""Finite born-child parity admission; external I/O is fake."""

import importlib
import json
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from pydantic import SecretStr

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local import service_bootstrap_context as context
from ai_workshop.infrastructure.local.service_bootstrap_context import VerifiedLaunchCapability
from ai_workshop.labs.rag.indexing.recovery import RagAliasParityFailure, RagAliasParityResult

MODULE = "ai_workshop.labs.rag.indexing.access_epoch_parity_cli"


def test_cli_module_exists() -> None:
    assert importlib.util.find_spec(MODULE) is not None


@pytest.fixture
def case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    cli = importlib.import_module(MODULE)
    profile, epoch = uuid4(), uuid4()
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        secret_key=SecretStr("synthetic-secret-value-only-32-characters"),
        elasticsearch_url="https://localhost:9200",
        elasticsearch_ca_certs=Path("synthetic-ca.pem"),
        elasticsearch_access_epoch_id=epoch,
        elasticsearch_access_epoch=2,
        elasticsearch_role="writer",
        elasticsearch_api_key=SecretStr("synthetic-key"),
    )
    capability = VerifiedLaunchCapability(
        uuid4(),
        "parity",
        MODULE,
        os.getpid(),
        "12345",
        "writer",
        epoch,
        2,
        "synthetic-id",
        "a" * 64,
        (profile,),
    )
    monkeypatch.setattr(context, "_current", capability)
    monkeypatch.setattr(cli, "process_identity", lambda _pid: ("12345", Path("python.exe")))
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("# synthetic\n", encoding="utf-8")
    calls: list[object] = []
    value = SimpleNamespace(
        cli=cli,
        profile=profile,
        settings=settings,
        capability=capability,
        calls=calls,
        result=RagAliasParityResult(1, 1, 0),
        failure=None,
    )

    def load(**kwargs: Any) -> Settings:
        assert kwargs == {"_env_file": tmp_path / ".env"}
        return settings

    async def verify(actual: Settings, *, writer: bool) -> None:
        assert actual is settings and writer is True
        calls.append("admission")

    class Reconciler:
        def __init__(self, actual: Settings) -> None:
            assert actual is settings
            calls.append("constructed")

        async def run_once(self, *, profile_id: object) -> RagAliasParityResult:
            calls.append(profile_id)
            if value.failure is not None:
                raise value.failure
            return value.result  # type: ignore[no-any-return]

    monkeypatch.setattr(cli, "Settings", load)
    monkeypatch.setattr(cli, "verify_original_runtime", verify)
    monkeypatch.setattr(cli, "SqlAlchemyRagAliasParityReconciler", Reconciler)
    return value


async def test_exact_scoped_success(case: Any) -> None:
    assert await case.cli.run(case.profile) == {
        "profile_id": str(case.profile),
        "claimed": 1,
        "reconciled": 1,
        "failed": 0,
        "error_code": None,
    }
    assert case.calls == ["admission", "constructed", case.profile]


@pytest.mark.parametrize(
    "change",
    [
        {"service": "worker"},
        {"module": "celery"},
        {"role": "reader"},
        {"pid": 1},
        {"creation_time": "999"},
        {"epoch_id": uuid4()},
        {"ordinal": 3},
        {"bound_ids": ()},
        {"bound_ids": (uuid4(),)},
        {"bound_ids": (uuid4(), uuid4())},
        {"ordinal": True},
    ],
)
async def test_wrong_birth_denied_before_callback(
    case: Any,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, Any],
) -> None:
    monkeypatch.setattr(context, "_current", replace(case.capability, **change))
    assert (await case.cli.run(case.profile))["error_code"] == "access_epoch_parity_denied"
    assert case.calls == []


async def test_legacy_operator_denied(case: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(context, "_current", None)
    assert (await case.cli.run(case.profile))["error_code"] == "access_epoch_parity_denied"
    assert case.calls == []


@pytest.mark.parametrize("mode", ["runtime_failure", "birth_replaced", "settings_changed"])
async def test_late_change_blocks_callback(
    case: Any,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    async def verify(_settings: Settings, *, writer: bool) -> None:
        if mode == "runtime_failure":
            raise RuntimeError("SYNTHETIC-PRIVATE-BODY")
        if mode == "birth_replaced":
            monkeypatch.setattr(context, "_current", replace(case.capability))
        else:
            case.settings.elasticsearch_access_epoch = 3

    monkeypatch.setattr(case.cli, "verify_original_runtime", verify)
    result = await case.cli.run(case.profile)
    assert result["error_code"] == "access_epoch_parity_denied"
    assert case.calls == []
    assert "PRIVATE" not in str(result)


@pytest.mark.parametrize("counts", [(0, 0, 0), (1, 0, 1), (2, 2, 0), (True, 1, 0)])
async def test_empty_failed_or_overscoped_is_not_success(case: Any, counts: Any) -> None:
    case.result = RagAliasParityResult(*counts)
    assert (await case.cli.run(case.profile))["error_code"] == "access_epoch_parity_failed"
    assert case.calls.count(case.profile) == 1


async def test_frozen_gate_failure_no_retry(case: Any) -> None:
    case.result = RagAliasParityResult(
        1,
        0,
        1,
        (RagAliasParityFailure(case.profile, "rag_index_attempt_busy", True, "PRIVATE-BODY"),),
    )
    assert await case.cli.run(case.profile) == {
        "profile_id": str(case.profile),
        "claimed": 1,
        "reconciled": 0,
        "failed": 1,
        "error_code": "access_epoch_parity_failed",
    }
    assert case.calls.count(case.profile) == 1


async def test_exception_body_never_enters_summary(case: Any) -> None:
    case.failure = RuntimeError("SYNTHETIC-PRIVATE-BODY")
    result = await case.cli.run(case.profile)
    assert result["error_code"] == "access_epoch_parity_failed"
    assert "PRIVATE" not in str(result)
    assert case.calls.count(case.profile) == 1


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--all"],
        ["--profile", "PRIVATE-BODY"],
        ["--profile", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"],
        ["--profile", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"],
        ["--profile", str(uuid4()), "--profile", str(uuid4())],
        ["--profile", str(uuid4()), "--extra", "PRIVATE-BODY"],
        ["--profile=" + str(uuid4())],
    ],
)
def test_parser_body_free_denial(case: Any, args: list[str], capsys: Any) -> None:
    with pytest.raises(ValueError, match="^access_epoch_parity_arguments$"):
        case.cli.parser().parse_args(args)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_main_closed_summary(case: Any, capsys: Any) -> None:
    case.cli.main(["--profile", str(case.profile)])
    output = json.loads(capsys.readouterr().out)
    assert output["reconciled"] == 1 and output["error_code"] is None
    with pytest.raises(SystemExit) as exc:
        case.cli.main(["--profile", "PRIVATE-BODY"])
    assert exc.value.code == 2
    assert json.loads(capsys.readouterr().out) == {
        "profile_id": None,
        "claimed": 0,
        "reconciled": 0,
        "failed": 0,
        "error_code": "access_epoch_parity_arguments",
    }


@pytest.mark.parametrize("mode", ["environment", "epoch", "role", "missing_env", "query_failed"])
async def test_original_settings_and_lifetime_required(
    case: Any,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    if mode == "environment":
        case.settings.environment = "test"
    elif mode == "epoch":
        case.settings.elasticsearch_access_epoch_id = None
    elif mode == "role":
        case.settings.elasticsearch_role = "collector"
    elif mode == "missing_env":
        (case.cli.PROJECT_ROOT / ".env").unlink()
    else:

        def fail(_pid: int) -> None:
            raise OSError("PRIVATE-PROCESS-DETAIL")

        monkeypatch.setattr(case.cli, "process_identity", fail)
    assert (await case.cli.run(case.profile))["error_code"] == "access_epoch_parity_denied"
    assert case.calls == []


@pytest.mark.parametrize(
    "result",
    [
        None,
        {"claimed": 1, "reconciled": 1, "failed": 0},
        RagAliasParityResult(1, 1, 1),
        RagAliasParityResult(1, 1.0, 0),  # type: ignore[arg-type]  # Deliberate invalid wire count.
        RagAliasParityResult(
            1, 1, 0, (RagAliasParityFailure(uuid4(), "PRIVATE-CODE", True, "PRIVATE-BODY"),)
        ),
    ],
)
async def test_malformed_or_ambiguous_success_denied(case: Any, result: Any) -> None:
    case.result = result
    output = await case.cli.run(case.profile)
    assert output["error_code"] == "access_epoch_parity_failed"
    assert "PRIVATE" not in json.dumps(output)
    assert case.calls.count(case.profile) == 1


def test_main_failure_is_nonzero_and_has_no_private_diagnostic(case: Any, capsys: Any) -> None:
    case.failure = RuntimeError("PRIVATE-BODY")
    with pytest.raises(SystemExit) as exc:
        case.cli.main(["--profile", str(case.profile)])
    assert exc.value.code == 1
    captured = capsys.readouterr()
    assert captured.err == "" and "PRIVATE" not in captured.out
    assert json.loads(captured.out)["error_code"] == "access_epoch_parity_failed"
