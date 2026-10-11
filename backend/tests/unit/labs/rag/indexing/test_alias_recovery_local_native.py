"""Synthetic files/stub OS observations, without actual host, Docker or network I/O."""

import base64
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_workshop.labs.rag.indexing.alias_recovery_local_native import POWERSHELL_EXE

synthetic_windows = pytest.mark.skipif(
    sys.platform != "win32" or not Path(POWERSHELL_EXE).is_file(),
    reason="requires the fixed original Windows PowerShell runtime for synthetic helper execution",
)


HOST_FAILURE_CASES = (
    "host_ancestor_reparse",
    "host_binary_reparse",
    "host_identity_unverified",
    "host_path_unverified",
    "host_open_failed",
    "host_signature_unverified",
    "host_hash_unverified",
    "host_binary_changed",
    "host_observation_failed",
)


def test_host_pins_only_the_fixed_original_node_alias_and_checks_its_physical_file():
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import HOST_SCRIPT

    assert "public static SafeFileHandle NodeAliasDirectory()" in HOST_SCRIPT
    assert "C:\\nvm4w\\nodejs" in HOST_SCRIPT
    assert '"v24.18.0"' in HOST_SCRIPT
    assert "[AliasHostFile]::NodePhysicalPath($aliasProbe.SafeFileHandle)" in HOST_SCRIPT
    assert "[AliasHostFile]::NodeAliasDirectory()" in HOST_SCRIPT
    assert "[AliasHostFile]::Identity($aliasProbe.SafeFileHandle,$path)" in HOST_SCRIPT
    assert "host_ancestor_reparse" in HOST_SCRIPT


@pytest.mark.parametrize("diagnostic", HOST_FAILURE_CASES)
async def test_nonzero_host_preserves_only_fixed_failure_protocol(monkeypatch, diagnostic):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    monkeypatch.setattr(native, "_verify_powershell", lambda path: None)

    def run(argv, **kwargs):
        assert argv == native.command_argv(native.FixedCommand.HOST)
        return SimpleNamespace(
            returncode=1,
            stdout=json.dumps({"diagnostic": diagnostic}).encode(),
            stderr=b"synthetic-private-stderr",
        )

    monkeypatch.setattr(native.subprocess, "run", run)
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await native.NativeCommandExecutor().run(native.FixedCommand.HOST)
    assert caught.value.diagnostic == diagnostic


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"[]",
        b'"host_ancestor_reparse"',
        b'{"diagnostic":null}',
        b'{"diagnostic":23}',
        b'{"diagnostic":"unknown-private"}',
        b'{"diagnostic":"unknown_client_process"}',
        b'{"diagnostic":"host_ancestor_reparse_private"}',
        b'{"diagnostic":"host_ancestor_reparse","path":"synthetic-private"}',
        b'{"diagnostic":"host_ancestor_reparse","diagnostic":"host_ancestor_reparse"}',
        b'{"diagnostic":"host_ancestor_reparse"}{}',
        b"private-command",
        b"\xff",
        b"",
        b'{"diagnostic":"host_ancestor_reparse"}' + b" " * 257,
    ],
)
async def test_host_protocol_rejects_malformed_private_duplicate_or_oversized_payload(
    monkeypatch, payload
):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    monkeypatch.setattr(native, "_verify_powershell", lambda path: None)
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout=payload, stderr=b'{"diagnostic":"host_ancestor_reparse"}'
        ),
    )
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await native.NativeCommandExecutor().run(native.FixedCommand.HOST)
    assert caught.value.diagnostic == "local_command_failed"


@pytest.mark.parametrize("command", ["context", "wsl_state", "stop", "untyped_host"])
async def test_host_protocol_is_not_accepted_from_another_command_or_string(monkeypatch, command):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    monkeypatch.setattr(native, "_verify_powershell", lambda path: None)
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout=b'{"diagnostic":"host_ancestor_reparse"}', stderr=b""
        ),
    )
    value = "host" if command == "untyped_host" else native.FixedCommand(command)
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await native.NativeCommandExecutor().run(value)
    assert caught.value.diagnostic == "local_command_failed"


async def test_host_protocol_success_and_timeout_never_become_refusal_evidence(monkeypatch):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    monkeypatch.setattr(native, "_verify_powershell", lambda path: None)
    inventory = b'{"processes":[],"tcp":[],"frontend_tcp":[],"helper_pid":7}'
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=inventory, stderr=b""),
    )
    assert await native.NativeCommandExecutor().run(native.FixedCommand.HOST) == inventory.decode()

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("synthetic", 45)

    monkeypatch.setattr(native.subprocess, "run", timeout)
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await native.NativeCommandExecutor().run(native.FixedCommand.HOST)
    assert caught.value.diagnostic == "local_command_failed"


async def test_host_protocol_zero_exit_diagnostic_is_not_successful_host_inventory(monkeypatch):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    payload = b'{"diagnostic":"host_ancestor_reparse"}'
    monkeypatch.setattr(native, "_verify_powershell", lambda path: None)
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout=payload, stderr=b""),
    )
    observed = await native.NativeCommandExecutor().run(native.FixedCommand.HOST)
    assert observed == payload.decode()
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        native.validate_host(json.loads(observed), ())
    assert caught.value.diagnostic == "local_enumeration_incomplete"


async def test_host_protocol_code_survives_native_and_cli_preflight_without_mutation(monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native
    from ai_workshop.labs.rag.indexing.alias_recovery_cli import execute, parser
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

    backend, _, _ = native_backend(monkeypatch)
    backend.executor = native.NativeCommandExecutor()
    snapshot = AliasOperationSnapshot(
        uuid4(),
        "local_rag_indexes",
        "cluster",
        "active",
        uuid4(),
        uuid4(),
        (),
        datetime(2026, 9, 21, tzinfo=UTC),
        "legacy_unknown",
    )

    async def identity(self):
        return SimpleNamespace(cluster_uuid="cluster")

    async def history(self, *args):
        return "a" * 64

    async def clients(self):
        return await self.executor.run(native.FixedCommand.HOST)

    async def preview(*args):
        return snapshot

    monkeypatch.setattr(native.OriginalWindowsBackend, "identity", identity)
    monkeypatch.setattr(native.OriginalWindowsBackend, "history", history)
    monkeypatch.setattr(native.OriginalWindowsBackend, "clients_absent", clients)
    monkeypatch.setattr(native, "_verify_powershell", lambda path: None)
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout=b'{"diagnostic":"host_ancestor_reparse"}', stderr=b""
        ),
    )
    args = parser().parse_args(
        ["preflight", "--operation", str(snapshot.operation_id), "--actor", str(uuid4())]
    )
    result = await execute(SimpleNamespace(preview=preview), args, backend)
    assert result["diagnostic"] == "host_ancestor_reparse"
    assert result["preflight"] == "blocked" and result["termination_proven"] is False
    assert result["parity"] == "not_run"


def run_synthetic_host(paths, *, fault="", repeat=False, expect_failure=False, node_alias=None):
    """Only synthetic files and stub OS observations enter the real HOST helper."""
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
        HOST_SCRIPT,
        POWERSHELL_EXE,
    )

    stats_path = Path(paths[0]).parent.parent / "synthetic-counters.json"
    fixture = json.dumps(
        {
            "paths": [str(path) for path in paths],
            "fault": fault,
            "stats": str(stats_path),
            "alias": str(node_alias[0]) if node_alias else None,
            "target": str(node_alias[1]) if node_alias else None,
        }
    )
    fixture64 = base64.b64encode(fixture.encode()).decode()
    prelude = r"""
$fixture=([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('FIXTURE'))|ConvertFrom-Json)
$script:sigs=0; $script:hashes=0; $script:writeDenied=$false; $script:replaceDenied=$false
$script:cleanupVisited=0
function Save-Counters {
 [IO.File]::WriteAllText($fixture.stats,(@{sigs=$script:sigs;hashes=$script:hashes;
 cleanup_visited=$script:cleanupVisited}|ConvertTo-Json -Compress))
}
function Get-CimInstance {
 param($ClassName)
 if($ClassName -ne 'Win32_Process'){throw 'Unexpected synthetic class'}
 $i=0
 foreach($path in $fixture.paths){$i++; [PSCustomObject]@{ProcessId=$i;ParentProcessId=0;
 CreationDate=[DateTimeOffset]'2026-10-01T00:00:00Z';Name='node.exe';
 CommandLine='synthetic';ExecutablePath=$path}}
}
function Get-NetTCPConnection {
 if($fixture.fault -eq 'unknown'){throw 'host_ancestor_reparse:synthetic-private'}
 @()
}
function Get-AuthenticodeSignature {
 param($LiteralPath)
 $script:sigs++
 Save-Counters
 if($fixture.fault -eq 'signature' -or
  ($fixture.fault -eq 'signature_second' -and $script:sigs -eq 2)){
  throw 'Synthetic signature failure'
 }
 try{[IO.File]::WriteAllText($LiteralPath,'tampered')}catch{$script:writeDenied=$true}
 try{[IO.Directory]::Move([IO.Path]::GetDirectoryName($LiteralPath),
 [IO.Path]::GetDirectoryName($LiteralPath)+'-moved')}catch{$script:replaceDenied=$true}
 [PSCustomObject]@{Status='Valid';SignerCertificate=[PSCustomObject]@{Subject='Synthetic signer'}}
}
function Get-FileHash {
 param($Algorithm,$LiteralPath,$InputStream)
 $script:hashes++
 Save-Counters
 if($fixture.fault -eq 'dispose'){
  $extra=[PSCustomObject]@{}
  if($script:hashes -eq 1){
   $extra|Add-Member ScriptMethod Dispose {throw 'Synthetic disposal failure'}
  }else{
   $extra|Add-Member ScriptMethod Dispose {$script:cleanupVisited++;Save-Counters}
  }
  $files.Add($extra)
 }
 if($fixture.fault -eq 'hash' -or
  ($fixture.fault -eq 'hash_second' -and $script:hashes -eq 2)){throw 'Synthetic hash failure'}
 if($InputStream){
  Microsoft.PowerShell.Utility\Get-FileHash -Algorithm $Algorithm -InputStream $InputStream
 }
 else{Microsoft.PowerShell.Utility\Get-FileHash -Algorithm $Algorithm -LiteralPath $LiteralPath}
}
if($fixture.alias){
 $null=New-Item -ItemType SymbolicLink -Path $fixture.alias -Target $fixture.target
}
if($fixture.fault -eq 'reparse'){
 $parent=[IO.Path]::GetDirectoryName($fixture.paths[0]);$link=$parent+'-link'
 $null=New-Item -ItemType Junction -Path $link -Target $parent
 $fixture.paths[0]=[IO.Path]::Combine($link,'node.exe')
}
if($fixture.fault -eq 'locked'){
 $writer=[IO.File]::Open($fixture.paths[0],[IO.FileMode]::Open,
  [IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
}
""".replace("FIXTURE", fixture64)
    host_script = HOST_SCRIPT
    if node_alias:
        host_script = host_script.replace(r"C:\nvm4w\nodejs", str(node_alias[0])).replace(
            "9a4eb5f1c29c6a2e93852ead46b999e284a6a5ca8bab4d4e241d587d025a52de",
            hashlib.sha256(b"public-node-binary").hexdigest(),
        )
    script = prelude + "\n$hostBlock={\n" + host_script + "\n}\n"
    if expect_failure:
        # Direct stdout is essential: a pipeline/assignment would swallow the
        # failure object before production exit1 terminates the entire child.
        script += "& $hostBlock\n"
    else:
        script += "$observations=@();\n"
        script += "$observations+=(& $hostBlock|ConvertFrom-Json)\n"
        if repeat:
            script += "$observations+=(& $hostBlock|ConvertFrom-Json)\n"
    script += r"""
$cleanup=$false
try{[IO.File]::WriteAllText($fixture.paths[0],'after');$cleanup=$true}catch{}
[PSCustomObject]@{failed=$false;sigs=$script:sigs;hashes=$script:hashes;
 write_denied=$script:writeDenied;replace_denied=$script:replaceDenied;
 cleanup=$cleanup;observations=$observations}|ConvertTo-Json -Depth 9 -Compress
"""
    script_path = stats_path.parent / "synthetic-host-helper.ps1"
    script_path.write_text(script, encoding="utf-8")
    result = subprocess.run(
        [
            POWERSHELL_EXE,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script_path),
        ],
        capture_output=True,
        check=False,
        timeout=45,
    )
    if expect_failure:
        assert result.returncode == 1, "Synthetic helper did not exit with its refusal"
    payload = json.loads(result.stdout.decode("utf-8-sig"))
    if result.returncode == 0:
        return payload
    assert result.returncode == 1 and set(payload) == {"diagnostic"}
    counts = json.loads(stats_path.read_text()) if stats_path.exists() else {"sigs": 0, "hashes": 0}
    for path in paths:
        Path(path).write_bytes(b"after-exit")
    return {
        "failed": True,
        "diagnostic": payload["diagnostic"],
        "returncode": result.returncode,
        "observations": [],
        "cleanup": True,
        **counts,
    }


@synthetic_windows
@pytest.mark.parametrize("change", ["valid", "wrong_version", "wrong_binary"])
def test_fixed_node_alias_uses_handle_derived_physical_identity_and_original_binary(
    tmp_path, change
):
    # Creating another symlink requires a privilege this user does not have.
    # Read the already existing original alias; never attempt writes or rename
    # against its directories/binary. Negative cases change only the helper's
    # expected version/hash, not the installed link, binary or configuration.
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
        HOST_SCRIPT,
        NODE_SHA,
        POWERSHELL_EXE,
    )

    alias = Path(r"C:\nvm4w\nodejs\node.exe")
    if not alias.is_file():
        pytest.skip("The fixed original NVM alias is not installed on this host")
    script = (
        r"""
function Get-CimInstance {
 param($ClassName)
 if($ClassName -ne 'Win32_Process'){throw 'Unexpected synthetic class'}
 [PSCustomObject]@{ProcessId=1;ParentProcessId=0;
 CreationDate=[DateTimeOffset]'2026-10-01T00:00:00Z';Name='node.exe';
 CommandLine='synthetic';ExecutablePath='C:\nvm4w\nodejs\node.exe'}
}
function Get-NetTCPConnection { @() }
"""
        + HOST_SCRIPT
    )
    if change == "wrong_version":
        script = script.replace('"v24.18.0"', '"v99.0.0"')
    elif change == "wrong_binary":
        script = script.replace(NODE_SHA, "a" * 64)
    script_path = tmp_path / "readonly-original-node-helper.ps1"
    script_path.write_text(script, encoding="utf-8")
    completed = subprocess.run(
        [POWERSHELL_EXE, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(script_path)],
        capture_output=True,
        check=False,
        timeout=45,
    )
    result = json.loads(completed.stdout.decode("utf-8-sig"))
    if change == "valid":
        assert completed.returncode == 0
        assert result["processes"][0]["binary_sha256"] == NODE_SHA
        assert result["processes"][0]["signature_status"] == "Valid"
    else:
        assert completed.returncode == 1
        assert result["diagnostic"] == (
            "host_path_unverified" if change == "wrong_version" else "host_binary_changed"
        )


@synthetic_windows
def test_host_helper_shares_only_protected_binary_checks_within_fresh_inventory(tmp_path):
    first, second = tmp_path / "first" / "node.exe", tmp_path / "second" / "node.exe"
    for path, body in [(first, b"public-one"), (second, b"public-two")]:
        path.parent.mkdir()
        path.write_bytes(body)
    result = run_synthetic_host([first, first, second], repeat=True)
    assert result["failed"] is False and result["cleanup"] is True
    assert result["sigs"] == 4 and result["hashes"] == 4
    assert result["write_denied"] is True and result["replace_denied"] is True
    for observation in result["observations"]:
        assert len(observation["processes"]) == 3
        assert [p["pid"] for p in observation["processes"]] == [1, 2, 3]
        assert [p["binary_sha256"] for p in observation["processes"]] == [
            hashlib.sha256(b"public-one").hexdigest(),
            hashlib.sha256(b"public-one").hexdigest(),
            hashlib.sha256(b"public-two").hexdigest(),
        ]


@synthetic_windows
@pytest.mark.parametrize("fault", ["signature", "hash", "signature_second", "hash_second"])
def test_host_helper_failure_closes_every_protected_file_handle(tmp_path, fault):
    paths = [tmp_path / "first" / "node.exe", tmp_path / "second" / "node.exe"]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b"public")
    result = run_synthetic_host(paths, fault=fault, expect_failure=True)
    assert result["failed"] is True and result["observations"] == []
    assert result["diagnostic"] == (
        "host_signature_unverified" if fault.startswith("signature") else "host_hash_unverified"
    )
    assert result["cleanup"] is True
    for path in paths:
        path.write_bytes(b"released")


@synthetic_windows
def test_host_helper_rejects_ambiguous_path_before_any_signature_check(tmp_path):
    directory = tmp_path / "binary"
    directory.mkdir()
    binary = directory / "node.exe"
    binary.write_bytes(b"public")
    result = run_synthetic_host([str(directory) + "/../binary/node.exe"], expect_failure=True)
    assert result["failed"] is True and result["sigs"] == result["hashes"] == 0
    assert result["diagnostic"] == "host_path_unverified"
    assert result["cleanup"] is True


@synthetic_windows
@pytest.mark.parametrize("fault", ["reparse", "locked"])
def test_host_helper_denies_reparse_or_existing_writer_without_unlocked_fallback(tmp_path, fault):
    path = tmp_path / "binary" / "node.exe"
    path.parent.mkdir()
    path.write_bytes(b"public")
    result = run_synthetic_host([path], fault=fault, expect_failure=True)
    assert result["failed"] is True and result["sigs"] == result["hashes"] == 0
    assert result["diagnostic"] == (
        "host_ancestor_reparse" if fault == "reparse" else "host_open_failed"
    )
    assert result["cleanup"] is True


@synthetic_windows
def test_host_helper_cleanup_fault_still_visits_all_handles_then_emits_generic_denial(tmp_path):
    paths = [tmp_path / "first" / "node.exe", tmp_path / "second" / "node.exe"]
    for path in paths:
        path.parent.mkdir()
        path.write_bytes(b"public")
    result = run_synthetic_host(paths, fault="dispose", expect_failure=True)
    assert result["diagnostic"] == "host_observation_failed" and result["returncode"] == 1
    assert result["cleanup_visited"] == 1 and result["cleanup"] is True


@synthetic_windows
def test_host_helper_does_not_classify_arbitrary_exception_text_as_internal_refusal(tmp_path):
    path = tmp_path / "binary" / "node.exe"
    path.parent.mkdir()
    path.write_bytes(b"public")
    result = run_synthetic_host([path], fault="unknown", expect_failure=True)
    assert result["diagnostic"] == "host_observation_failed" and result["returncode"] == 1
    assert result["cleanup"] is True and result["observations"] == []


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com:9200",
        "https://127.0.0.1:9200",
        "http://127.0.0.1:9201",
        "http://user:secret@127.0.0.1:9200",
        "http://127.0.0.1:9200/proxy",
        "http://127.0.0.1:9200?x=1",
        "http://127.0.0.1:9200#x",
        "http://localhost:9200",
    ],
)
def test_only_exact_direct_historical_origin_is_supported(url):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import validate_endpoint

    with pytest.raises(LocalRecoveryRefusal):
        validate_endpoint(url, {})


@pytest.mark.parametrize("key", ["HTTP_PROXY", "https_proxy", "ALL_PROXY", "NO_PROXY"])
def test_ambient_proxy_is_not_trusted_even_with_a_no_proxy_exception(key):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import validate_endpoint

    with pytest.raises(LocalRecoveryRefusal):
        validate_endpoint("http://127.0.0.1:9200", {key: "private-secret"})


def host():
    return {"processes": [], "tcp": [], "portproxy": "", "distros": ["docker-desktop"]}


@pytest.mark.parametrize("command", ["stop", "start", "unknown", "host"])
async def test_readonly_executor_denies_mutations_and_untyped_values_before_delegate(command):
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    runner = FixedExecutor()
    executor = native.ReadOnlyCommandExecutor(runner)
    value = native.FixedCommand(command) if command in {"stop", "start"} else command
    with pytest.raises(native.LocalRecoveryRefusal):
        await executor.run(value)
    assert runner.commands == []
    assert await executor.run(native.FixedCommand.CONTEXT)
    assert runner.commands == [native.FixedCommand.CONTEXT]


async def test_fixed_deployment_slot_inventory_is_explicitly_readonly():
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    class Slots:
        commands = []

        async def run(self, command):
            self.commands.append(command)
            return "[]"

    runner = Slots()
    executor = native.ReadOnlyCommandExecutor(runner)
    assert await executor.run(native.FixedCommand.ORIGINAL_SLOT_INVENTORY) == "[]"
    assert runner.commands == [native.FixedCommand.ORIGINAL_SLOT_INVENTORY]
    argv = native.command_argv(native.FixedCommand.ORIGINAL_SLOT_INVENTORY)
    assert argv[:3] == (native.DOCKER_EXE, "--host", "npipe:////./pipe/dockerDesktopLinuxEngine")
    assert argv[3:6] == ("ps", "--all", "--no-trunc")


async def test_native_preflight_reuses_live_checks_with_positive_readonly_capability(monkeypatch):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    backend, runner, _ = native_backend(monkeypatch)
    calls = []

    async def identity(self):
        assert isinstance(self.executor, native.ReadOnlyCommandExecutor)
        calls.append("identity")
        return SimpleNamespace(cluster_uuid="cluster")

    async def history(self, snapshot, observed):
        calls.append("history")
        return "a" * 64

    async def clients(self):
        calls.append("clients")
        await self.executor.run(native.FixedCommand.STOP)

    monkeypatch.setattr(native.OriginalWindowsBackend, "identity", identity)
    monkeypatch.setattr(native.OriginalWindowsBackend, "history", history)
    monkeypatch.setattr(native.OriginalWindowsBackend, "clients_absent", clients)
    with pytest.raises(native.LocalRecoveryRefusal):
        await backend.preflight(SimpleNamespace(cluster_uuid="cluster"))
    assert calls == ["identity", "history", "clients"] and runner.commands == []


@pytest.mark.parametrize("fault", [None, "identity", "history", "clients"])
async def test_native_preflight_fresh_checks_preserve_causal_state_and_bound_stage_errors(
    monkeypatch,
    fault,
):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    backend, runner, _ = native_backend(monkeypatch)
    calls = []
    original_identity = native.OriginalWindowsBackend.identity

    async def identity(self):
        calls.append("identity")
        assert self._allowed is None
        if fault == "identity":
            raise RuntimeError("synthetic-private-identity")
        return await original_identity(self)

    async def history(self, snapshot, observed):
        calls.append("history")
        assert observed.cluster_uuid == snapshot.cluster_uuid == "cluster"
        if fault == "history":
            raise RuntimeError("synthetic-private-history")
        return "a" * 64

    async def clients(self):
        calls.append("clients")
        self._allowed = ()
        if fault == "clients":
            raise RuntimeError("synthetic-private-clients")

    monkeypatch.setattr(native.OriginalWindowsBackend, "identity", identity)
    monkeypatch.setattr(native.OriginalWindowsBackend, "history", history)
    monkeypatch.setattr(native.OriginalWindowsBackend, "clients_absent", clients)
    snapshot = SimpleNamespace(cluster_uuid="cluster")
    if fault:
        with pytest.raises(native.LocalRecoveryRefusal) as caught:
            await backend.preflight(snapshot)
        assert caught.value.diagnostic == f"preflight_{fault}_blocked"
        assert "private" not in str(caught.value)
        assert (
            calls
            == ["identity", "history", "clients"][
                : ["identity", "history", "clients"].index(fault) + 1
            ]
        )
    else:
        assert await backend.preflight(snapshot) is None
        assert await backend.preflight(snapshot) is None
        assert calls == ["identity", "history", "clients"] * 2
    assert backend._allowed is None and backend._infrastructure_sha256 is None
    assert not any(
        command in {native.FixedCommand.STOP, native.FixedCommand.START}
        for command in runner.commands
    )


@pytest.mark.parametrize("stage", ["identity", "history", "clients"])
@pytest.mark.parametrize(
    "diagnostic",
    [
        "local_command_failed",
        "unknown_client_process",
        "collector_controller_unverified",
        "wsl_infrastructure_unverified",
        "preflight_clients_blocked",
        "unknown_client_process_private-token",
        "C:/synthetic-private/command",
        None,
    ],
)
async def test_native_preflight_preserves_only_positive_safe_diagnostics(
    monkeypatch, stage, diagnostic
):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    backend, runner, _ = native_backend(monkeypatch)
    calls = []

    def observe(current):
        calls.append(current)
        if current == stage:
            if diagnostic is None:
                raise RuntimeError("synthetic-private-exception")
            raise native.LocalRecoveryRefusal(diagnostic)

    async def identity(self):
        observe("identity")
        return SimpleNamespace(cluster_uuid="cluster")

    async def history(self, snapshot, observed):
        observe("history")
        return "a" * 64

    async def clients(self):
        observe("clients")

    monkeypatch.setattr(native.OriginalWindowsBackend, "identity", identity)
    monkeypatch.setattr(native.OriginalWindowsBackend, "history", history)
    monkeypatch.setattr(native.OriginalWindowsBackend, "clients_absent", clients)
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await backend.preflight(SimpleNamespace(cluster_uuid="cluster"))
    safe = diagnostic in {
        "local_command_failed",
        "unknown_client_process",
        "collector_controller_unverified",
        "wsl_infrastructure_unverified",
        "preflight_clients_blocked",
    }
    assert caught.value.diagnostic == (diagnostic if safe else f"preflight_{stage}_blocked")
    assert caught.value.__suppress_context__ is True
    assert "private" not in caught.value.diagnostic
    assert (
        calls
        == ["identity", "history", "clients"][: ["identity", "history", "clients"].index(stage) + 1]
    )
    assert runner.commands == []


@pytest.mark.parametrize(
    "process",
    [
        {"pid": 1, "created_at": "2026-09-30T00:00:00Z", "name": "python.exe", "command": ""},
        {
            "pid": 1,
            "created_at": "2026-09-30T00:00:00Z",
            "name": "python.exe",
            "command": "old-cli",
        },
        {"pid": 1, "created_at": "2026-09-30T00:00:00Z", "name": "node.exe", "command": "unknown"},
        {"pid": 1, "created_at": "2026-09-30T00:00:00Z", "name": "ssh.exe", "command": "unknown"},
        {
            "pid": 1,
            "created_at": "2026-09-30T00:00:00Z",
            "name": "powershell.exe",
            "command": "ai_workshop.worker",
        },
    ],
)
def test_unknown_or_unreadable_runtime_is_not_excluded(process):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import validate_host

    data = host()
    data["processes"] = [process]
    with pytest.raises(LocalRecoveryRefusal):
        validate_host(data, ())


def test_exact_pid_lifetime_command_required_and_pid_reuse_rejected():
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
        ProcessLifetime,
        validate_host,
    )

    p = {
        "pid": 1,
        "created_at": "2026-09-30T00:00:00Z",
        "name": "python.exe",
        "command": "exact",
        "executable": "C:/python.exe",
        "parent_pid": 2,
    }
    allowed = ProcessLifetime.from_observation(p)
    data = host()
    data["processes"] = [p]
    assert isinstance(validate_host(data, (allowed,)), str)
    changed = deepcopy(p)
    changed["created_at"] = "2026-10-01T00:00:00Z"
    data["processes"] = [changed]
    with pytest.raises(LocalRecoveryRefusal):
        validate_host(data, (allowed,))


@pytest.mark.parametrize(
    "change",
    [
        {"processes": None},
        {"tcp": None},
        {"distros": ["docker-desktop", "Ubuntu"]},
        {"portproxy": "::1 9200 ::1 9201"},
        {"portproxy": "127.0.0.1 9200 127.0.0.1 9201"},
        {"tcp": [{"pid": 5, "state": "Established", "local_port": 9200}]},
        {"tcp": [{"pid": 5, "state": "Listen", "local_port": 9200}]},
    ],
)
def test_incomplete_enumeration_user_wsl_forwarder_or_unknown_live_connection_fails(change):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import validate_host

    data = host() | change
    with pytest.raises(LocalRecoveryRefusal):
        validate_host(data, ())


def test_timewait_pid_zero_is_closed_residue():
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import validate_host

    data = host() | {"tcp": [{"pid": 0, "state": "TimeWait", "local_port": 9200}]}
    assert isinstance(validate_host(data, ()), str)


def test_all_fixed_commands_use_absolute_executable_and_no_caller_arguments():
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand, command_argv

    for command in FixedCommand:
        args = command_argv(command)
        assert Path(args[0]).is_absolute()
        assert isinstance(args, tuple)
    assert command_argv(FixedCommand.STOP)[-1] == command_argv(FixedCommand.START)[-1]


WORKING_POWERSHELL = (
    r"C:\Program Files\WindowsApps\Microsoft.PowerShell_7.6.6.0_arm64__8wekyb3d8bbwe\pwsh.exe"
)


def synthetic_powershell_binary(monkeypatch, failure=None):
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    events = []
    binary = b"synthetic-official-powershell"
    monkeypatch.setattr(native, "POWERSHELL_SHA", hashlib.sha256(binary).hexdigest(), raising=False)
    monkeypatch.setattr(Path, "is_symlink", lambda path: failure == "symlink")
    monkeypatch.setattr(Path, "is_file", lambda path: failure != "missing")

    def read_bytes(path):
        assert native._path(str(path)) == native._path(WORKING_POWERSHELL)
        events.append("hash")
        return b"synthetic-private-changed-binary" if failure == "changed" else binary

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    return events


def test_fixed_helper_argv_pins_working_versioned_powershell_and_hash():
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    assert native.POWERSHELL_EXE == WORKING_POWERSHELL
    assert (
        native.POWERSHELL_SHA == "abb215e4d87889c85a18333a310b1dbdae33e78a25e13dc7cf129fbdaea848e0"
    )
    for command in (native.FixedCommand.HOST, native.FixedCommand.WSL_STATE):
        assert native.command_argv(command)[0] == WORKING_POWERSHELL


@pytest.mark.parametrize("command_name", ["HOST", "WSL_STATE"])
async def test_native_helper_verifies_pinned_binary_before_fixed_subprocess(
    monkeypatch, command_name
):
    from types import SimpleNamespace

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    events = synthetic_powershell_binary(monkeypatch)
    command = native.FixedCommand[command_name]

    def run(argv, **kwargs):
        assert argv == native.command_argv(command)
        assert argv[0] == WORKING_POWERSHELL
        assert kwargs["shell"] is False
        assert events == ["hash"]
        events.append("spawn")
        return SimpleNamespace(returncode=0, stdout=b"{}")

    monkeypatch.setattr(native.subprocess, "run", run)
    assert await native.NativeCommandExecutor().run(command) == "{}"
    assert events == ["hash", "spawn"]


@pytest.mark.parametrize("failure", ["moved", "changed", "missing", "symlink"])
@pytest.mark.parametrize("command_name", ["HOST", "WSL_STATE"])
async def test_native_helper_wrong_path_or_binary_refuses_before_spawn(
    monkeypatch,
    command_name,
    failure,
):
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    events = synthetic_powershell_binary(monkeypatch, failure)
    if failure == "moved":
        original_argv = native.command_argv
        monkeypatch.setattr(
            native,
            "command_argv",
            lambda command: (r"C:\synthetic-private-moved\pwsh.exe", *original_argv(command)[1:]),
        )

    def forbidden(*args, **kwargs):
        pytest.fail("unverified PowerShell spawned")

    monkeypatch.setattr(native.subprocess, "run", forbidden)
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await native.NativeCommandExecutor().run(native.FixedCommand[command_name])
    assert caught.value.diagnostic == "powershell_binary_unverified"
    assert "private" not in str(caught.value)
    assert events == (["hash"] if failure == "changed" else [])


def test_exact_windowsapps_controller_requires_pinned_binary_and_payload(monkeypatch):
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    events = synthetic_powershell_binary(monkeypatch)
    payload = "synthetic-fixed-payload"
    command = f'"{WORKING_POWERSHELL}" -NoProfile -Command {payload}'
    assert native._controller_matches(command, WORKING_POWERSHELL, {payload})
    assert events == ["hash"]
    for changed in (
        r"C:\synthetic-private-moved\pwsh.exe",
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        WORKING_POWERSHELL.replace("7.6.6.0", "7.6.7.0"),
    ):
        assert not native._controller_matches(
            command.replace(WORKING_POWERSHELL, changed), changed, {payload}
        )
    synthetic_powershell_binary(monkeypatch, "changed")
    assert not native._controller_matches(command, WORKING_POWERSHELL, {payload})


class FixedExecutor:
    def __init__(self):
        from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
            CONTAINER,
            DAEMON,
            NETWORK,
            PEERS,
            FixedCommand,
        )

        self.commands = []
        self.container = {
            "Id": CONTAINER,
            "Created": "2026-09-01T00:00:00Z",
            "Image": "immutable-image",
            "Config": {"Env": ["discovery.type=single-node"]},
            "HostConfig": {
                "PortBindings": {"9200/tcp": [{"HostIp": "127.0.0.1", "HostPort": "9200"}]},
                "AutoRemove": False,
                "Privileged": False,
            },
            "State": {
                "Running": True,
                "Restarting": False,
                "Pid": 5,
                "StartedAt": "2026-09-29T00:00:00Z",
                "FinishedAt": "2026-09-28T00:00:00Z",
            },
            "Mounts": [
                {
                    "Type": "volume",
                    "Destination": "/usr/share/elasticsearch/data",
                    "RW": True,
                    "Driver": "local",
                    "Name": "original-data",
                }
            ],
            "NetworkSettings": {"Networks": {"original": {"NetworkID": NETWORK}}},
        }
        self.responses = {
            FixedCommand.CONTEXT: [
                {
                    "Name": "desktop-linux",
                    "Endpoints": {"docker": {"Host": "npipe:////./pipe/dockerDesktopLinuxEngine"}},
                }
            ],
            FixedCommand.DAEMON: {"ID": DAEMON, "OSType": "linux"},
            FixedCommand.CONTAINER: [self.container],
            FixedCommand.NETWORK: [{"Containers": dict.fromkeys(PEERS, {})}],
            FixedCommand.PEERS: [
                {
                    "Id": pid,
                    "Config": {
                        "Labels": {
                            "com.docker.compose.project": "ai-workshop",
                            "com.docker.compose.service": service,
                        }
                    },
                }
                for pid, service in zip(PEERS[:2], ("redis", "postgres"), strict=True)
            ],
            FixedCommand.RUNNING: "\n".join(PEERS),
        }

    async def run(self, command):
        from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

        assert isinstance(command, FixedCommand)
        self.commands.append(command)
        if command == FixedCommand.STOP:
            self.container["State"].update(Running=False, Pid=0, FinishedAt="2026-10-01T00:00:00Z")
            self.responses[FixedCommand.NETWORK][0]["Containers"].pop(self.container["Id"])
            return self.container["Id"]
        value = self.responses[command]
        return value if isinstance(value, str) else json.dumps(value)


class Reader:
    def __init__(self):
        self.paths = []
        self.responses = {
            "/": {"cluster_uuid": "cluster"},
            "/_cluster/health": {
                "number_of_nodes": 1,
                "number_of_data_nodes": 1,
                "status": "yellow",
            },
            "/_cluster/state/master_node,nodes": {
                "cluster_uuid": "cluster",
                "master_node": "node",
                "nodes": {"node": {"ephemeral_id": "old"}},
            },
            "/_nodes/jvm": {
                "_nodes": {"total": 1, "successful": 1, "failed": 0},
                "nodes": {"node": {"jvm": {"start_time_in_millis": 1790640001000}}},
            },
        }
        self.responses["/_cluster/state/nodes"] = {
            key: deepcopy(value)
            for key, value in self.responses["/_cluster/state/master_node,nodes"].items()
            if key != "master_node"
        }

    async def read(self, path):
        self.paths.append(path)
        return self.responses[path]


def native_backend(monkeypatch):
    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import OriginalWindowsBackend

    monkeypatch.setattr("os.environ", {})
    runner, reader = FixedExecutor(), Reader()
    settings = Settings(
        _env_file=None,
        secret_key="offline-synthetic-secret-1234567890",
        rag_index_store_id="local_rag_indexes",
        rag_index_cluster_uuid="cluster",
    )
    return (
        OriginalWindowsBackend(settings, Path("C:/synthetic-workspace"), runner, reader),
        runner,
        reader,
    )


async def test_fixed_native_identity_observes_persistent_single_node_without_mutation(monkeypatch):
    backend, runner, reader = native_backend(monkeypatch)
    identity = await backend.identity()
    assert identity.cluster_uuid == "cluster" and identity.running
    assert reader.paths == [
        "/",
        "/_cluster/health",
        "/_cluster/state/master_node,nodes",
        "/_nodes/jvm",
    ]
    assert all(command.value not in {"stop", "start"} for command in runner.commands)


async def test_metric_selective_reader_returns_master_only_when_requested():
    reader = Reader()
    assert "master_node" not in await reader.read("/_cluster/state/nodes")
    state = await reader.read("/_cluster/state/master_node,nodes")
    assert state["master_node"] in state["nodes"]


async def test_fixed_direct_reader_requests_explicit_master_and_nodes_without_proxy(monkeypatch):
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs == {"trust_env": False, "follow_redirects": False, "timeout": 10}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url):
            from types import SimpleNamespace

            calls.append(url)
            return SimpleNamespace(status_code=200, content=b"{}", json=lambda: {})

    monkeypatch.setattr(native.httpx, "AsyncClient", Client)
    assert await native.DirectElasticsearchReader().read("/_cluster/state/master_node,nodes") == {}
    assert calls == ["http://127.0.0.1:9200/_cluster/state/master_node,nodes"]


@pytest.mark.parametrize("path", ["/_cluster/state/_all", "/_cluster/state/nodes?local=true"])
async def test_fixed_direct_reader_rejects_unknown_metrics_before_transport(monkeypatch, path):
    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    def forbidden(**kwargs):
        pytest.fail("unknown metric initialized a transport")

    monkeypatch.setattr(native.httpx, "AsyncClient", forbidden)
    with pytest.raises(native.LocalRecoveryRefusal, match="rag_alias_proof_invalid"):
        await native.DirectElasticsearchReader().read(path)


async def test_exact_stopped_container_has_no_live_network_endpoint(monkeypatch):
    backend, runner, _ = native_backend(monkeypatch)
    identity = await backend.identity()
    stopped = await backend.stop(identity)
    assert not stopped.running and stopped.persistent == identity.persistent
    assert [command.value for command in runner.commands].count("stop") == 1


@pytest.mark.parametrize(
    "changed",
    [
        "context",
        "daemon",
        "container",
        "mount",
        "config",
        "peer",
        "node",
        "multi",
        "cluster",
        "empty_ephemeral",
    ],
)
async def test_native_identity_or_topology_changes_are_denied_before_mutation(monkeypatch, changed):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import FixedCommand

    backend, runner, reader = native_backend(monkeypatch)
    if changed == "context":
        runner.responses[FixedCommand.CONTEXT][0]["Endpoints"]["docker"]["Host"] = "ssh://remote"
    elif changed == "daemon":
        runner.responses[FixedCommand.DAEMON]["ID"] = "other"
    elif changed == "container":
        runner.container["Id"] = "f" * 64
    elif changed == "mount":
        runner.container["Mounts"][0]["Type"] = "bind"
    elif changed == "config":
        runner.container["HostConfig"]["PortBindings"]["9200/tcp"][0]["HostIp"] = "0.0.0.0"
    elif changed == "peer":
        runner.responses[FixedCommand.NETWORK][0]["Containers"]["unknown"] = {}
    elif changed == "node":
        reader.responses["/_cluster/state/master_node,nodes"]["master_node"] = "other"
    elif changed == "cluster":
        reader.responses["/_cluster/state/master_node,nodes"]["cluster_uuid"] = "other"
    elif changed == "empty_ephemeral":
        reader.responses["/_cluster/state/master_node,nodes"]["nodes"]["node"]["ephemeral_id"] = ""
    else:
        reader.responses["/_cluster/health"]["number_of_nodes"] = 2
    with pytest.raises(LocalRecoveryRefusal):
        await backend.identity()
    assert all(command.value not in {"stop", "start"} for command in runner.commands)


async def test_history_reads_only_fixed_pinned_original_records_and_binds_container(monkeypatch):
    from uuid import uuid4

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native
    from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

    backend, _, _ = native_backend(monkeypatch)
    identity = await backend.identity()
    snapshot = AliasOperationSnapshot(
        uuid4(),
        "local_rag_indexes",
        "cluster",
        "active",
        uuid4(),
        uuid4(),
        (),
        datetime(2026, 9, 21, tzinfo=UTC),
        "legacy_unknown",
    )
    paths = tuple(native.HISTORY_FILES)
    content = {path: f"synthetic-{index}".encode() for index, path in enumerate(paths)}
    monkeypatch.setattr(
        native,
        "HISTORY_FILES",
        {path: hashlib.sha256(value).hexdigest() for path, value in content.items()},
    )
    reads = []

    def read_bytes(path):
        relative = path.relative_to(backend.root).as_posix()
        reads.append(relative)
        return content[relative]

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    monkeypatch.setattr(Path, "is_symlink", lambda _: False)
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: '{"cluster_uuid":"cluster"}')
    monkeypatch.setattr(
        native,
        "dotenv_values",
        lambda *a, **kw: {
            "AI_WORKSHOP_ENVIRONMENT": "local",
            "AI_WORKSHOP_ELASTICSEARCH_URL": "http://127.0.0.1:9200",
        },
    )
    digest = await backend.history(snapshot, identity)
    assert set(reads) == set(paths)
    assert len(digest) == 64
    changed = replace(identity, mount_sha256="f" * 64)
    assert await backend.history(snapshot, changed) != digest
    content[paths[0]] = b"private-secret-modified-record"
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await backend.history(snapshot, identity)
    assert caught.value.diagnostic == "original_history_changed"
    assert "private-secret" not in str(caught.value)
    with pytest.raises(native.LocalRecoveryRefusal):
        await backend.history(replace(snapshot, created_at=native.HISTORY_AT), identity)


async def test_fixed_host_collector_pins_own_cli_helper_and_positive_wsl_lifetimes(monkeypatch):
    import base64
    import os
    import subprocess
    import sys

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native
    from tests.unit.labs.rag.indexing.test_alias_recovery_local_wsl import boundary

    backend, runner, _ = native_backend(monkeypatch)
    rows, state = boundary()
    own_pid = 100
    own_argv = [
        str(backend.root / "backend/.venv/Scripts/python.exe"),
        "-m",
        native.MODULE,
        "recover",
        "--operation",
        "11111111-1111-1111-1111-111111111111",
    ]
    monkeypatch.setattr(sys, "orig_argv", own_argv)
    monkeypatch.setattr(os, "getpid", lambda: own_pid)
    own = {
        "pid": own_pid,
        "parent_pid": 0,
        "created_at": "2026-10-01T00:00:00Z",
        "name": "python.exe",
        "command": subprocess.list2cmdline(own_argv),
        "executable": own_argv[0],
    }
    helper_args = native.command_argv(native.FixedCommand.HOST)
    helper = {
        "pid": 101,
        "parent_pid": own_pid,
        "created_at": "2026-10-01T00:00:01Z",
        "name": "powershell.exe",
        "command": subprocess.list2cmdline(helper_args),
        "executable": native.POWERSHELL_EXE,
    }
    host_data = {"processes": [*rows, own, helper], "tcp": [], "helper_pid": 101}
    runner.responses.update(
        {
            native.FixedCommand.WSL_STATE: state,
            native.FixedCommand.HOST: host_data,
            native.FixedCommand.WSL: "docker-desktop",
            native.FixedCommand.PORTPROXY: "",
        }
    )
    registry = [
        {
            "phase": "frontend",
            "pid": 9999,
            "launcher_pid": 9998,
            "started_at": "2026-09-29T00:00:00Z",
        }
    ]
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: json.dumps(registry))
    digest, observed = await backend.clients_absent()
    assert len(digest) == 64 and observed.tzinfo is not None
    assert native.FixedCommand.STOP not in runner.commands
    assert base64.b64decode(helper_args[-1]).decode("utf-16le") == native.HOST_SCRIPT
    rows[4]["created_at"] = "2026-10-01T00:00:02Z"
    with pytest.raises(native.LocalRecoveryRefusal) as caught:
        await backend.clients_absent()
    assert caught.value.diagnostic == "infrastructure_lifetime_changed"


def test_only_fixed_env_clear_controller_or_exact_direct_cli_payload_is_supported(monkeypatch):
    import base64

    from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
        MODULE,
        POWERSHELL_EXE,
        _controller_matches,
        controller_payload,
    )

    root = Path("C:/synthetic-workspace")
    synthetic_powershell_binary(monkeypatch)
    argv = (
        str(root / "backend/.venv/Scripts/python.exe"),
        "-m",
        MODULE,
        "recover",
        "--operation",
        "11111111-1111-1111-1111-111111111111",
        "--actor",
        "22222222-2222-2222-2222-222222222222",
        "--request",
        "33333333-3333-3333-3333-333333333333",
    )
    payload = controller_payload(root, argv)
    direct = f'"{POWERSHELL_EXE}" -NoProfile -Command {payload}'
    assert _controller_matches(direct, POWERSHELL_EXE, {payload})
    encoded = base64.b64encode(payload.encode("utf-16le")).decode()
    assert _controller_matches(
        f'"{POWERSHELL_EXE}" -EncodedCommand {encoded}', POWERSHELL_EXE, {payload}
    )
    for changed in (
        direct + "\nStart-Process python",
        direct.replace("11111111", "99999999"),
        direct.replace("Set-Location", "Write-Output"),
    ):
        assert not _controller_matches(changed, POWERSHELL_EXE, {payload})


def test_exact_thin_launcher_base_interpreter_controller_and_pnpm_frontend(monkeypatch):
    import os
    import subprocess
    import sys

    from ai_workshop.labs.rag.indexing import alias_recovery_local_native as native

    backend, _, _ = native_backend(monkeypatch)
    synthetic_powershell_binary(monkeypatch)
    own_argv = [
        str(backend.root / "backend/.venv/Scripts/python.exe"),
        "-m",
        native.MODULE,
        "recover",
        "--operation",
        "11111111-1111-1111-1111-111111111111",
    ]
    monkeypatch.setattr(sys, "orig_argv", own_argv)
    monkeypatch.setattr(os, "getpid", lambda: 100)
    base = str(Path(sys._base_executable).resolve())

    def process(pid, parent, name, executable, command, created="2026-10-01T00:00:00Z"):
        return {
            "pid": pid,
            "parent_pid": parent,
            "name": name,
            "executable": executable,
            "command": command,
            "created_at": created,
        }

    payload = native.controller_payload(backend.root, tuple(own_argv))
    rows = [
        process(100, 101, "python.exe", base, subprocess.list2cmdline(own_argv)),
        process(101, 102, "python.exe", own_argv[0], subprocess.list2cmdline(own_argv)),
        process(
            102,
            0,
            "pwsh.exe",
            native.POWERSHELL_EXE,
            f'"{native.POWERSHELL_EXE}" -NoProfile -Command {payload}',
        ),
    ]
    pnpm = (
        backend.root
        / "frontend/node_modules/.pnpm/next@synthetic"
        / "node_modules/next/dist/server/lib/start-server.js"
    )
    node = "C:/synthetic-tools/node.exe"
    rows.extend(
        [
            process(
                200,
                201,
                "node.exe",
                node,
                subprocess.list2cmdline([node, str(pnpm)]),
                "2026-09-29T01:04:31.985272Z",
            ),
            process(
                201,
                999,
                "node.exe",
                node,
                subprocess.list2cmdline(
                    [
                        node,
                        "node_modules/next/dist/bin/next",
                        "dev",
                        "--hostname",
                        "127.0.0.1",
                        "--port",
                        "5173",
                    ]
                ),
                "2026-09-29T01:04:31.021403Z",
            ),
        ]
    )
    for row in rows[-2:]:
        row.update(binary_sha256=native.NODE_SHA, signature_status="Valid")
    registry = [
        {
            "phase": "frontend",
            "pid": 200,
            "launcher_pid": 201,
            "started_at": "2026-09-29T01:04:31.985272Z",
        }
    ]
    monkeypatch.setattr(Path, "read_text", lambda *a, **kw: json.dumps(registry))
    original_resolve = Path.resolve

    def resolve(path, strict=False):
        if strict:
            return pnpm
        return original_resolve(path)

    monkeypatch.setattr(Path, "resolve", resolve)
    host_data = {
        "processes": rows,
        "tcp": [],
        "portproxy": "",
        "distros": ["docker-desktop"],
        "frontend_tcp": [
            {"pid": 200, "state": "Listen", "local_port": 5173, "local_address": "127.0.0.1"}
        ],
    }
    allowed = backend._initial_allowed(host_data)
    assert {p.pid for p in allowed} == {100, 101, 102, 200, 201}
    assert len(native.validate_host(host_data, allowed)) == 64
    rows[4]["command"] += " --extra private-secret"
    with pytest.raises(native.LocalRecoveryRefusal):
        backend._initial_allowed(host_data)
    with pytest.raises(native.LocalRecoveryRefusal):
        native.validate_host(host_data, allowed)
