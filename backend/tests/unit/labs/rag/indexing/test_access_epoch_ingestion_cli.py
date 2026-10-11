"""One normal registered ingestion, no broker/model/native/database calls in tests."""

import asyncio
import importlib
import json
import os
from contextlib import asynccontextmanager
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
from ai_workshop.labs.rag.ingestion.domain import RagIngestionBusy, RagIngestionError

MODULE = "ai_workshop.labs.rag.indexing.access_epoch_ingestion_cli"


def test_ingestion_module_exists() -> None:
    assert importlib.util.find_spec(MODULE) is not None


@pytest.fixture
def case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    cli = importlib.import_module(MODULE)
    job, epoch, projection, profile, processing, asset = (uuid4() for _ in range(6))
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        secret_key=SecretStr("synthetic-secret-32-characters-only"),
        elasticsearch_url="https://localhost:9200",
        elasticsearch_ca_certs=Path("synthetic.pem"),
        elasticsearch_access_epoch_id=epoch,
        elasticsearch_access_epoch=1,
        elasticsearch_role="writer",
        elasticsearch_api_key=SecretStr("synthetic-key"),
        rag_index_cluster_uuid="cluster",
        rag_index_store_id="rag",
    )
    born = VerifiedLaunchCapability(
        uuid4(),
        "ingestion",
        MODULE,
        os.getpid(),
        "123",
        "writer",
        epoch,
        1,
        "key",
        "a" * 64,
        (job,),
    )
    target = cli._Target(job, projection, profile, processing, asset)
    value = SimpleNamespace(
        cli=cli,
        job=job,
        projection=projection,
        settings=settings,
        born=born,
        target=target,
        calls=[],
        error=None,
        result=projection,
        actual_read=cli._read_target,
    )
    monkeypatch.setattr(context, "_current", born)
    monkeypatch.setattr(cli, "process_identity", lambda _pid: ("123", Path("python.exe")))
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("# synthetic\n", encoding="utf-8")

    def load(**kwargs: Any) -> Settings:
        assert kwargs == {"_env_file": tmp_path / ".env"}
        return settings

    async def runtime(actual: Settings, *, writer: bool) -> None:
        assert actual is settings and writer is True
        value.calls.append("runtime")

    async def read(actual: Settings, job_id: object, *, completed: bool) -> Any:
        assert actual is settings and job_id == job
        value.calls.append("read_ready" if completed else "admission")
        return target

    class Workflow:
        async def run(self, job_id: object) -> Any:
            assert job_id == job
            value.calls.append("run")
            if value.error is not None:
                raise value.error
            return value.result

        async def fail(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("A direct child has no job-wide failure authority")

    def factory(actual: Settings) -> Workflow:
        assert actual is settings
        value.calls.append("factory")
        return Workflow()

    monkeypatch.setattr(cli, "Settings", load)
    monkeypatch.setattr(cli, "verify_original_runtime", runtime)
    monkeypatch.setattr(cli, "_read_target", read)
    monkeypatch.setattr(cli, "create_rag_ingestion_workflow", factory)
    return value


async def test_normal_exact_job_once_and_pending_dispatch_report(case: Any) -> None:
    assert await case.cli.run(case.job) == {
        "job_id": str(case.job),
        "projection_id": str(case.projection),
        "workflow_completed": True,
        "dispatch": "pending",
        "error_code": None,
    }
    assert case.calls == ["runtime", "admission", "factory", "run", "read_ready"]


@pytest.mark.parametrize(
    "changes",
    [
        {"service": "worker"},
        {"module": "celery"},
        {"role": "reader"},
        {"pid": 1},
        {"creation_time": "456"},
        {"ordinal": 2},
        {"epoch_id": uuid4()},
        {"bound_ids": ()},
        {"bound_ids": (uuid4(),)},
    ],
)
async def test_wrong_birth_denied_before_any_callback(
    case: Any, monkeypatch: Any, changes: Any
) -> None:
    monkeypatch.setattr(context, "_current", replace(case.born, **changes))
    assert (await case.cli.run(case.job))["error_code"] == "access_epoch_ingestion_denied"
    assert case.calls == []


@pytest.mark.parametrize("boundary", ["runtime", "target", "birth_after_target"])
async def test_fresh_admission_denial_stops_normal_work(
    case: Any, monkeypatch: Any, boundary: str
) -> None:
    async def fail(*_args: object, **_kwargs: object) -> Any:
        if boundary == "birth_after_target":
            monkeypatch.setattr(context, "_current", replace(case.born))
            return case.target
        raise ValueError("PRIVATE-FROZEN-GATE")

    monkeypatch.setattr(
        case.cli, "verify_original_runtime" if boundary == "runtime" else "_read_target", fail
    )
    output = await case.cli.run(case.job)
    assert output["error_code"] == "access_epoch_ingestion_denied"
    assert "factory" not in case.calls
    assert "PRIVATE" not in json.dumps(output)


@pytest.mark.parametrize(
    "error,code",
    [
        (RagIngestionBusy(), "ingestion_owner_unsettled"),
        (
            RagIngestionError("rag_index_writer_unconfirmed", "PRIVATE", retryable=False),
            "ingestion_owner_unsettled",
        ),
        (
            RagIngestionError("rag_index_attempt_busy", "PRIVATE", retryable=False),
            "ingestion_owner_unsettled",
        ),
        (OSError("PRIVATE"), "ingestion_retryable_unsettled"),
        (
            RagIngestionError("parser_failed", "PRIVATE", retryable=False),
            "terminal_failure_unsettled",
        ),
        (RuntimeError("PRIVATE"), "terminal_failure_unsettled"),
    ],
)
async def test_failed_run_never_fails_shared_job_or_retries(
    case: Any, error: Exception, code: str
) -> None:
    case.error = error
    output = await case.cli.run(case.job)
    assert output["error_code"] == code and output["workflow_completed"] is False
    assert case.calls.count("run") == 1 and "read_ready" not in case.calls
    assert "PRIVATE" not in json.dumps(output)


async def test_cancel_propagates_without_false_completion(case: Any) -> None:
    case.error = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await case.cli.run(case.job)
    assert case.calls.count("run") == 1 and "read_ready" not in case.calls


async def test_returned_projection_is_not_ready_proof(case: Any, monkeypatch: Any) -> None:
    async def read(*_args: object, completed: bool) -> Any:
        if completed:
            raise ValueError("PRIVATE-READBACK")
        return case.target

    monkeypatch.setattr(case.cli, "_read_target", read)
    result = await case.cli.run(case.job)
    assert result["workflow_completed"] is False
    assert result["error_code"] == "ingestion_completion_unconfirmed"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--job", "PRIVATE"],
        ["--all"],
        ["--job", "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"],
        ["--job=" + str(uuid4())],
        ["--job", str(uuid4()), "--job", str(uuid4())],
    ],
)
def test_parser_finite_body_free(case: Any, args: list[str], capsys: Any) -> None:
    with pytest.raises(ValueError, match="^access_epoch_ingestion_arguments$"):
        case.cli.parser().parse_args(args)
    assert capsys.readouterr().out == ""


def test_main_closed_failure_output(case: Any, capsys: Any) -> None:
    case.error = RuntimeError("PRIVATE")
    with pytest.raises(SystemExit) as captured:
        case.cli.main(["--job", str(case.job)])
    assert captured.value.code == 1
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out and output.err == ""
    assert json.loads(output.out)["error_code"] == "terminal_failure_unsettled"


@pytest.fixture
def target_row(case: Any) -> dict[str, object]:
    return {
        "job_id": case.job,
        "projection_id": case.projection,
        "indexing_profile_id": case.target.indexing_profile_id,
        "document_processing_profile_id": case.target.document_processing_profile_id,
        "asset_version_id": case.target.asset_version_id,
        "job_status": "queued",
        "job_stage": "queued",
        "projection_status": "pending",
        "gate_state": "admitted",
        "open_alias": False,
        "dispatch_status": "pending",
        "source_valid": True,
        "profiles_valid": True,
        "command_valid": True,
        "parsed_element_count": None,
        "chunk_count": None,
        "embedding_count": None,
        "indexed_document_count": None,
        "index_alias_verified": False,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"gate_state": "frozen"},
        {"gate_state": None},
        {"open_alias": True},
        {"source_valid": False},
        {"profiles_valid": False},
        {"command_valid": False},
        {"job_id": uuid4()},
        {"job_status": "running"},
        {"projection_status": "ready"},
        {"dispatch_status": "claimed"},
        {"dispatch_status": "sent"},
        {"source_valid": 1},
    ],
)
def test_exact_target_gate_and_pending_contract(
    case: Any,
    target_row: dict[str, object],
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="access_epoch_ingestion_denied"):
        case.cli._decode_target(target_row | changes, case.job, completed=False)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"chunk_count": True},
        {"embedding_count": 4},
        {"index_alias_verified": False},
        {"job_stage": "indexing"},
    ],
)
def test_ready_requires_real_counts_and_alias_readback(
    case: Any,
    target_row: dict[str, object],
    changes: dict[str, object],
) -> None:
    ready = target_row | {
        "job_status": "succeeded",
        "job_stage": "ready",
        "projection_status": "ready",
        "parsed_element_count": 2,
        "chunk_count": 3,
        "embedding_count": 3,
        "indexed_document_count": 3,
        "index_alias_verified": True,
    }
    assert case.cli._decode_target(target_row, case.job, completed=False) == case.target
    if changes:
        with pytest.raises(ValueError):
            case.cli._decode_target(ready | changes, case.job, completed=True)
    else:
        assert case.cli._decode_target(ready, case.job, completed=True) == case.target


@pytest.mark.parametrize("mode", ["valid", "absent", "duplicate", "query_failure", "cancel"])
async def test_actual_target_reader_is_exact_scoped_and_always_disposes(
    case: Any,
    target_row: dict[str, object],
    monkeypatch: Any,
    mode: str,
) -> None:
    events: list[object] = []

    class Connection:
        async def execute(self, statement: Any, parameters: Any) -> Any:
            assert parameters == {"job": case.job, "cluster": "cluster"}
            assert str(statement).lstrip().startswith("SELECT ")
            events.append("query")
            if mode == "query_failure":
                raise OSError("PRIVATE-DATABASE")
            if mode == "cancel":
                raise asyncio.CancelledError()
            rows = [] if mode == "absent" else [target_row] * (2 if mode == "duplicate" else 1)
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))

    class Engine:
        @asynccontextmanager
        async def connect(self) -> Any:
            yield Connection()

        async def dispose(self) -> None:
            events.append("disposed")

    monkeypatch.setattr(case.cli, "create_engine", lambda _settings: Engine())
    if mode == "valid":
        assert await case.actual_read(case.settings, case.job, completed=False) == case.target
    elif mode == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await case.actual_read(case.settings, case.job, completed=False)
    else:
        with pytest.raises(ValueError, match="^access_epoch_ingestion_denied$"):
            await case.actual_read(case.settings, case.job, completed=False)
    assert events == ["query", "disposed"]


async def test_wrong_workflow_projection_or_changed_target_never_completes(case: Any) -> None:
    case.result = uuid4()
    result = await case.cli.run(case.job)
    assert result["workflow_completed"] is False
    assert result["error_code"] == "ingestion_completion_unconfirmed"
    assert "read_ready" not in case.calls
