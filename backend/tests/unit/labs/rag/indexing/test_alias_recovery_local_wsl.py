"""DockerDesktop infrastructure identity is positive, not a WSL name exemption."""

from copy import deepcopy

import pytest


def boundary():
    from ai_workshop.labs.rag.indexing.alias_recovery_local_wsl import BINARIES

    distro = "11111111-1111-1111-1111-111111111111"
    vm = "22222222-2222-2222-2222-222222222222"

    def process(pid, parent, binary, arguments, protected=False):
        path, digest, signer = BINARIES[binary]
        return {
            "pid": pid,
            "parent_pid": parent,
            "created_at": "2026-09-29T00:00:00Z",
            "name": binary,
            "executable": None if protected else path,
            "command": None if protected else f'"{path}" {arguments}'.rstrip(),
            "binary_sha256": digest,
            "signer": signer,
            "signature_status": "Valid",
        }

    bootstrap = (
        "-d docker-desktop -u root -e wsl-bootstrap "
        'run --base-image "C:/Program Files/Docker/Docker/resources/docker-desktop.iso" '
        '--cli-iso "C:/Program Files/Docker/Docker/resources/wsl/docker-wsl-cli.iso" '
        "--data-disk 33333333-3333-3333-3333-333333333333"
    )
    rows = [
        process(1, 0, "com.docker.backend.exe", ""),
        process(2, 1, "com.docker.backend.exe", "services"),
        process(3, 2, "system-wsl.exe", bootstrap),
        process(4, 3, "wsl.exe", bootstrap),
        process(
            5,
            4,
            "wslhost.exe",
            f"--distro-id {distro} --vm-id {vm} --handle 1 --event 2 --parent 3",
        ),
        process(6, 0, "wslservice.exe", "", True),
        process(7, 6, "wslhost.exe", f"--vm-id {vm} --handle 4"),
        process(8, 6, "wslrelay.exe", f"--mode 1 --vm-id {vm} --handle 5"),
    ]
    rows[2]["name"] = "wsl.exe"
    service_path, service_sha, signer = BINARIES["wslservice.exe"]
    state = {
        "docker_distros": [{"name": "docker-desktop", "id": distro}],
        "service": {
            "name": "WSLService",
            "state": "Running",
            "start_name": "LocalSystem",
            "pid": 6,
            "path": service_path,
            "binary_sha256": service_sha,
            "signature_status": "Valid",
            "signer": signer,
        },
    }
    return rows, state


def test_exact_scm_registered_distro_parent_chain_and_typed_vm_identity_are_required():
    from ai_workshop.labs.rag.indexing.alias_recovery_local_wsl import classify_infrastructure

    rows, state = boundary()
    result = classify_infrastructure(rows, state)
    assert result.allowed_pids == frozenset(range(1, 9))
    assert result.docker_listener_pids == frozenset({1, 2})
    assert len(result.sha256) == 64


@pytest.mark.parametrize(
    "change",
    [
        "scm_pid",
        "scm_account",
        "signature",
        "binary",
        "distro",
        "vm",
        "unknown_flag",
        "parent",
        "empty_command",
        "manual_wsl",
        "scm_absent",
    ],
)
def test_no_generic_signed_name_scm_descendant_or_guid_exemption(change):
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal
    from ai_workshop.labs.rag.indexing.alias_recovery_local_wsl import classify_infrastructure

    rows, state = boundary()
    if change == "scm_pid":
        state["service"]["pid"] = 99
    elif change == "scm_account":
        state["service"]["start_name"] = "Other"
    elif change == "signature":
        rows[4]["signature_status"] = "UnknownError"
    elif change == "binary":
        rows[4]["binary_sha256"] = "f" * 64
    elif change == "distro":
        state["docker_distros"][0]["id"] = "99999999-9999-9999-9999-999999999999"
    elif change == "vm":
        rows[6]["command"] = rows[6]["command"].replace("22222222", "99999999")
    elif change == "unknown_flag":
        rows[4]["command"] += " --execute private-secret"
    elif change == "parent":
        rows[4]["parent_pid"] = 99
    elif change == "empty_command":
        rows[4]["command"] = None
    elif change == "manual_wsl":
        extra = deepcopy(rows[3])
        extra.update(pid=99, command='"C:/Program Files/WSL/wsl.exe" -d docker-desktop -e curl')
        rows.append(extra)
    else:
        state["service"] = None
    with pytest.raises(LocalRecoveryRefusal):
        classify_infrastructure(rows, state)


def test_observed_empty_argv0_host_service_and_inherited_system_launcher_are_supported():
    from ai_workshop.labs.rag.indexing.alias_recovery_local_wsl import (
        BINARIES,
        classify_infrastructure,
    )

    rows, state = boundary()
    bootstrap = (
        "-d docker-desktop -u root -e wsl-bootstrap run "
        '--base-image "C:/Program Files/Docker/Docker/resources/docker-desktop.iso" '
        '--cli-iso "C:/Program Files/Docker/Docker/resources/wsl/docker-wsl-cli.iso" '
        "--data-disk 33333333-3333-3333-3333-333333333333"
    )
    for row in rows[2:4]:
        row["command"] = f'"{BINARIES["system-wsl.exe"][0]}" {bootstrap}'
    for row in (rows[4], rows[6], rows[7]):
        row["command"] = " " + row["command"].split('" ', 1)[1]
    result = classify_infrastructure(rows, state)
    assert result.allowed_pids == frozenset(range(1, 9))


def test_only_exact_docker_vpnkit_guest_launcher_is_supported():
    from ai_workshop.labs.rag.indexing.alias_recovery_local_wsl import (
        BINARIES,
        classify_infrastructure,
    )

    rows, state = boundary()
    proxy = "-d docker-desktop -e /usr/bin/vpnkit-bridge --pid-file=/run/vpnkit-bridge.pid guest"
    for row in rows[2:4]:
        row["command"] = f'"{BINARIES["system-wsl.exe"][0]}" {proxy}'
    assert classify_infrastructure(rows, state).allowed_pids == frozenset(range(1, 9))
    rows[2]["command"] += " --url private-secret"
    from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

    with pytest.raises(LocalRecoveryRefusal):
        classify_infrastructure(rows, state)
