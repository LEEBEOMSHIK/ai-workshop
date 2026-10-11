"""Original source authorization, with synthetic inventory and private storage."""

import copy
import hashlib
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.unit.labs.rag.indexing.test_access_epoch_app_retirement import app_case as _app_case

app_case = _app_case


def module():
    return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_original_apps")


async def test_only_source_issued_identity_is_protected_before_allowlist(app_case, monkeypatch):
    m = module()
    c = app_case
    reader = m.OriginalApplicationSourceReader()
    observation = m.ObservedOriginalApplications(uuid4(), c.allowlist.targets, b"synthetic source")
    reader._issued[observation] = observation

    async def observe():
        return observation

    monkeypatch.setattr(reader, "observe", observe)
    issuer = m.OriginalApplicationAllowlistIssuer(c.epoch, c.repo, c.journal, reader)
    value = await issuer.read_current()
    assert value.targets == observation.targets
    assert value.off_roles == ("worker", "beat")
    assert c.memory.files
    assert issuer.assert_issued(value) is None
    with pytest.raises(ValueError):
        issuer.assert_issued(replace(value))
    # Terminating one captured process does not revoke its original authorization.
    reader._issued[observation] = observation
    assert issuer.assert_issued(value) is None
    assert "synthetic source" not in repr(observation)


@pytest.mark.parametrize(
    "failure", ["unissued", "owner_lost", "generation", "existing_actions", "capture_tampered"]
)
async def test_copied_or_changed_source_never_grants_termination(app_case, monkeypatch, failure):
    m = module()
    c = app_case
    reader = m.OriginalApplicationSourceReader()
    observation = m.ObservedOriginalApplications(uuid4(), c.allowlist.targets, b"synthetic source")
    reader._issued[observation] = observation

    async def observe():
        if failure == "owner_lost":
            c.lock.close(c.owner)
        if failure == "generation":
            c.repo.state = replace(c.repo.state, executor_generation=str(uuid4()))
        return replace(observation) if failure == "unissued" else observation

    monkeypatch.setattr(reader, "observe", observe)
    issuer = m.OriginalApplicationAllowlistIssuer(c.epoch, c.repo, c.journal, reader)
    if failure == "existing_actions":
        c.repo.state = replace(c.repo.state, actions=(SimpleNamespace(),))
    if failure == "capture_tampered":
        value = await issuer.read_current()
        c.memory.files[next(iter(c.memory.files))] = b"tampered"
        with pytest.raises(ValueError):
            issuer.assert_issued(value)
    else:
        with pytest.raises(ValueError):
            await issuer.read_current()


def test_supervisor_source_is_a_closed_environment_cleanup_and_fixed_launch():
    m = module()
    root = m.PROJECT_ROOT
    valid = m._script_template(root)
    m.validate_original_supervisor(valid.encode(), root)
    for old, new in (
        ("Env:TASK_REVIEW_PASSWORD", "C:/unrelated/file"),
        ("AI_WORKSHOP_*", "*"),
        ("127.0.0.1", "0.0.0.0"),
        ("--port 18000", "--port 18001"),
        ("exit $LASTEXITCODE", "while ($true) { Start-Process python }"),
        ("Remove-Item -LiteralPath ('Env:' + $_.Name)", "Remove-Item -Recurse C:/projects"),
    ):
        with pytest.raises(ValueError):
            m.validate_original_supervisor(valid.replace(old, new).encode(), root)
    with pytest.raises(ValueError):
        m.validate_original_supervisor((valid + "\nStart-Process python").encode(), root)
    with pytest.raises(ValueError):
        m.validate_original_supervisor(valid.encode(), Path("C:/different-project"))


@pytest.fixture
def source_case(monkeypatch):
    m = module()
    python = m.PROJECT_ROOT / "backend/.venv/Scripts/python.exe"
    supervisor = m._SUPERVISOR_EXE
    script = m.PROJECT_ROOT / ".local-data/source-synthetic.ps1"
    report = b"synthetic public launch report"
    monkeypatch.setattr(m, "_REPORT_SHA256", hashlib.sha256(report).hexdigest())
    files = {
        m.PROJECT_ROOT / m._REPORT: report,
        script: m._script_template(m.PROJECT_ROOT).encode(),
    }
    monkeypatch.setattr(m, "_ordinary", lambda path, limit: files[path])
    rows = []
    times = {}
    for index, (role, pid) in enumerate(m._PIDS.items()):
        dt = m._START + m.timedelta(microseconds=300 - index * 100)
        span = dt - m.datetime(1601, 1, 1, tzinfo=m.UTC)
        ft = str((span.days * 86400 * 1000000 + span.seconds * 1000000 + span.microseconds) * 10)
        image = (
            Path(getattr(sys, "_base_executable", sys.executable))
            if role == "api"
            else python
            if role == "api_launcher"
            else supervisor
        )
        times[pid] = (ft, image)
        cmd = (
            '"' + str(python) + '" ' + " ".join(m._ARGS)
            if role != "api_supervisor"
            else f'"{supervisor}" -NoProfile -NonInteractive -File "{script}"'
        )
        rows.append(
            {
                "pid": pid,
                "parent_pid": (33656, 73132, 10)[index],
                "created_at": dt.isoformat(),
                "executable": str(image),
                "command": cmd,
                "name": image.name,
            }
        )
    rows.extend(
        [
            {"pid": 7824, "parent_pid": 30272, "command": "synthetic frontend", "name": "node.exe"},
            {"pid": 30272, "parent_pid": 5, "command": "synthetic launcher", "name": "node.exe"},
        ]
    )
    host = {
        "processes": rows,
        "tcp": [
            {"pid": 29536, "local_port": 18000, "local_address": "127.0.0.1", "state": "Listen"}
        ],
        "frontend_tcp": [{"pid": 7824, "local_port": 5173, "state": "Listen"}],
    }

    class Executor:
        calls = 0
        changed = None

        async def run(self, command):
            assert command == m.FixedCommand.HOST
            self.calls += 1
            return json.dumps(self.changed if self.calls > 1 and self.changed else host)

    executor = Executor()
    queries = []

    def query(pid):
        queries.append(pid)
        return times[pid]

    return SimpleNamespace(
        m=m,
        host=host,
        times=times,
        files=files,
        script=script,
        executor=executor,
        reader=m.OriginalApplicationSourceReader(executor, query),
        queries=queries,
    )


async def test_source_read_observes_original_chain_twice_without_process_control(source_case):
    c = source_case
    c.host["processes"].append({"pid": 4, "parent_pid": 0, "name": "System", "command": None})
    value = await c.reader.observe()
    assert c.reader.assert_issued(value) is None
    assert c.executor.calls == 2 and len(c.queries) == 6
    assert {p.pid for _, p in value.targets} == {29536, 33656, 73132}
    assert b"source-synthetic" in value.private_source


@pytest.mark.parametrize(
    "failure",
    [
        "script",
        "parent",
        "api_port",
        "worker",
        "python_unknown",
        "query_time",
        "query_image",
        "second_host",
        "outside_script",
        "duplicate_pid",
        "script_escape",
    ],
)
async def test_changed_actual_source_or_lifetime_has_no_issued_authority(source_case, failure):
    c = source_case
    if failure == "script":
        c.files[c.script] += b"\nStart-Process python"
    elif failure == "parent":
        c.host["processes"][0]["parent_pid"] = 10
    elif failure == "api_port":
        c.host["tcp"][0]["pid"] = 7824
    elif failure == "worker":
        c.host["processes"].append(
            {
                "pid": 12345,
                "name": "python.exe",
                "command": "python -m celery -A ai_workshop.worker:celery_app worker",
            }
        )
    elif failure == "python_unknown":
        c.host["processes"].append({"pid": 12345, "name": "python.exe", "command": None})
    elif failure == "query_time":
        _, path = c.times[29536]
        c.times[29536] = ("133700000000000003", path)
    elif failure == "query_image":
        ft, _ = c.times[29536]
        c.times[29536] = (ft, Path("C:/foreign/python.exe"))
    elif failure == "second_host":
        c.executor.changed = copy.deepcopy(c.host)
        c.executor.changed["processes"][0]["created_at"] = c.m._START.isoformat()
    elif failure == "outside_script":
        c.host["processes"][2]["command"] = c.host["processes"][2]["command"].replace(
            str(c.script), "C:/foreign/source.ps1"
        )
    elif failure == "script_escape":
        escaped = c.m.PROJECT_ROOT / ".local-data/../outside-source.ps1"
        c.files[escaped] = c.files[c.script]
        c.host["processes"][2]["command"] = c.host["processes"][2]["command"].replace(
            str(c.script), str(escaped)
        )
    else:
        c.host["processes"].append(copy.deepcopy(c.host["processes"][0]))
    with pytest.raises(ValueError, match="^original_application_source_denied$"):
        await c.reader.observe()
    assert not c.reader._issued
