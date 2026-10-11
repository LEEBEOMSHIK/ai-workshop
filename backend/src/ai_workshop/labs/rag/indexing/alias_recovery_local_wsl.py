"""Typed DockerDesktop infrastructure classification, never supplied as proof JSON."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from ai_workshop.labs.rag.indexing.alias_recovery_local import LocalRecoveryRefusal

BINARIES = {
    "com.docker.backend.exe": (
        "C:/Program Files/Docker/Docker/resources/com.docker.backend.exe",
        "a5762dbd2c04381fa9a17b6af8a452636c7ed136d875b06de66ec444b9e0ea0d",
        "Docker",
    ),
    "system-wsl.exe": (
        "C:/Windows/System32/wsl.exe",
        "a3af879a0c4345a7d34a10e734155e9c7cceeb24495e1ee1c9cfb5efb1f83079",
        "Microsoft",
    ),
    "wsl.exe": (
        "C:/Program Files/WSL/wsl.exe",
        "a926c38b061f08ab0e3e0f3848378663a240727ed3cad1c42d0f4fed4060fb6b",
        "Microsoft",
    ),
    "wslservice.exe": (
        "C:/Program Files/WSL/wslservice.exe",
        "486d1e275e6d113383b8ada6160678c4e81cb19810a949a9b9a8ac842ae16070",
        "Microsoft",
    ),
    "wslhost.exe": (
        "C:/Program Files/WSL/wslhost.exe",
        "e5c262743ac64ffc7074e84a04596bbdf80db4c300043848200ac71be32588e0",
        "Microsoft",
    ),
    "wslrelay.exe": (
        "C:/Program Files/WSL/wslrelay.exe",
        "5b9f1d04ca760021a4368b219e442b5b6b3a46550626d6c682fb784b57ec64f1",
        "Microsoft",
    ),
}


@dataclass(frozen=True, slots=True)
class InfrastructureClassification:
    allowed_pids: frozenset[int]
    docker_listener_pids: frozenset[int]
    sha256: str


def _deny() -> LocalRecoveryRefusal:
    return LocalRecoveryRefusal("wsl_infrastructure_unverified")


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise _deny()
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise _deny()
    return value


def _integer(value: object) -> int:
    if type(value) is not int or value < 0:
        raise _deny()
    return value


def _path(value: str) -> str:
    return value.replace("\\", "/").lower()


def _uuid(value: object) -> str:
    try:
        return str(UUID(_string(value).strip("{}")))
    except Exception:
        raise _deny() from None


def command_tokens(command: str) -> tuple[str, ...]:
    """Conservative Windows argument subset: whole quoted/unquoted tokens.

    Embedded quotes/escapes, glued quoted fragments and empty tokens are unsupported.
    Known infrastructure needs only whole-path quotes and plain typed flags.
    """
    pattern = re.compile(r'\s*(?:"([^"\r\n]+)"|([^\s"\r\n]+))')
    tokens: list[str] = []
    offset = 0
    while offset < len(command.rstrip()):
        match = pattern.match(command, offset)
        if match is None or (match.end() < len(command) and not command[match.end()].isspace()):
            raise _deny()
        token = match.group(1) or match.group(2)
        if not token or '"' in token:
            raise _deny()
        tokens.append(token)
        offset = match.end()
    if not tokens:
        raise _deny()
    return tuple(tokens)


def infrastructure_arguments(command: str, executable: str) -> tuple[str, ...]:
    tokens = command_tokens(command)
    first = _path(tokens[0])
    expected = _path(executable)
    if first == expected:
        return tokens[1:]
    if expected == _path(BINARIES["wsl.exe"][0]) and first == _path(BINARIES["system-wsl.exe"][0]):
        # The official runtime inherits System32 launcher's exact argv0.
        return tokens[1:]
    if (
        expected in {_path(BINARIES[name][0]) for name in ("wslhost.exe", "wslrelay.exe")}
        and command.startswith(" ")
        and first in {"--distro-id", "--vm-id", "--mode"}
    ):
        # CreateProcess uses a separately verified executable and an empty argv0.
        return tokens
    raise _deny()


def _signed(row: dict[str, object], binary: str) -> None:
    path, sha, signer = BINARIES[binary]
    if (
        _path(_string(row.get("executable"))) != _path(path)
        or row.get("binary_sha256") != sha
        or row.get("signature_status") != "Valid"
        or signer not in _string(row.get("signer"))
    ):
        raise _deny()


def _flags(arguments: tuple[str, ...], required: set[str]) -> dict[str, str]:
    if len(arguments) != 2 * len(required):
        raise _deny()
    pairs: dict[str, str] = {}
    for position in range(0, len(arguments), 2):
        key, value = arguments[position : position + 2]
        if key not in required or key in pairs:
            raise _deny()
        pairs[key] = value
    if set(pairs) != required:
        raise _deny()
    for key, value in pairs.items():
        if (
            key in {"--handle", "--event", "--parent"}
            and re.fullmatch(r"[0-9]{1,20}", value) is None
        ):
            raise _deny()
    return pairs


def _launcher(arguments: tuple[str, ...]) -> str:
    # Exact installed Docker modules, never arbitrary command tails.
    resources = "C:/Program Files/Docker/Docker/resources/"
    if (
        len(arguments) == 13
        and arguments[:5] == ("-d", "docker-desktop", "-u", "root", "-e")
        and arguments[5:8] == ("wsl-bootstrap", "run", "--base-image")
        and _path(arguments[8]) == _path(resources + "docker-desktop.iso")
        and arguments[9] == "--cli-iso"
        and _path(arguments[10]) == _path(resources + "wsl/docker-wsl-cli.iso")
        and arguments[11] == "--data-disk"
    ):
        _uuid(arguments[12])
        return "bootstrap"
    if arguments == (
        "-d",
        "docker-desktop",
        "-e",
        "/usr/bin/vpnkit-bridge",
        "--pid-file=/run/vpnkit-bridge.pid",
        "guest",
    ):
        return "vpnkit_guest"
    raise _deny()


def classify_infrastructure(
    processes: list[dict[str, object]],
    state: dict[str, object],
) -> InfrastructureClassification:
    try:
        relevant = [
            row
            for row in processes
            if _string(row.get("name")).lower().startswith(("wsl", "com.docker."))
        ]
        if not relevant:
            return InfrastructureClassification(
                frozenset(), frozenset(), hashlib.sha256(b"[]").hexdigest()
            )
        by_pid = {_integer(row.get("pid")): row for row in relevant}
        if len(by_pid) != len(relevant):
            raise _deny()
        for row in relevant:
            created = datetime.fromisoformat(_string(row.get("created_at")).replace("Z", "+00:00"))
            if created.tzinfo is None:
                raise _deny()
            parent_row = by_pid.get(_integer(row.get("parent_pid")))
            if (
                parent_row is not None
                and datetime.fromisoformat(
                    _string(parent_row.get("created_at")).replace("Z", "+00:00")
                )
                > created
            ):
                raise _deny()
        distros = state.get("docker_distros")
        if not isinstance(distros, list) or len(distros) != 1:
            raise _deny()
        distro = _object(distros[0])
        if distro.get("name") != "docker-desktop":
            raise _deny()
        distro_id = _uuid(distro.get("id"))
        service = _object(state.get("service"))
        service_pid = _integer(service.get("pid"))
        process = by_pid.get(service_pid)
        if (
            process is None
            or process.get("name") != "wslservice.exe"
            or service.get("name") != "WSLService"
            or service.get("state") != "Running"
            or service.get("start_name") != "LocalSystem"
        ):
            raise _deny()
        path, sha, signer = BINARIES["wslservice.exe"]
        if (
            _path(_string(service.get("path")).strip('"')) != _path(path)
            or service.get("binary_sha256") != sha
            or service.get("signature_status") != "Valid"
            or signer not in _string(service.get("signer"))
        ):
            raise _deny()
        # The protected exact SCM PID is the sole unreadable-command exception.
        if process.get("command") is not None or process.get("executable") is not None:
            _signed(process, "wslservice.exe")
            if infrastructure_arguments(_string(process.get("command")), path):
                raise _deny()
        allowed, docker, launchers, registered_hosts = {service_pid}, set(), {}, []
        docker_roots: set[int] = set()
        docker_services: set[int] = set()
        for pid, row in by_pid.items():
            if row.get("name") == "com.docker.backend.exe":
                _signed(row, "com.docker.backend.exe")
                args = infrastructure_arguments(
                    _string(row.get("command")), BINARIES["com.docker.backend.exe"][0]
                )
                if args not in {(), ("services",)}:
                    raise _deny()
                (docker_roots if not args else docker_services).add(pid)
                docker.add(pid)
                allowed.add(pid)
        if (
            len(docker_roots) != 1
            or len(docker_services) != 1
            or _integer(by_pid[next(iter(docker_services))].get("parent_pid")) not in docker_roots
        ):
            raise _deny()
        for pid, row in by_pid.items():
            if row.get("name") != "wsl.exe":
                continue
            binary = (
                "system-wsl.exe"
                if _path(_string(row.get("executable"))) == _path(BINARIES["system-wsl.exe"][0])
                else "wsl.exe"
            )
            _signed(row, binary)
            args = infrastructure_arguments(_string(row.get("command")), BINARIES[binary][0])
            kind = _launcher(args)
            parent_pid = _integer(row.get("parent_pid"))
            parent = by_pid.get(parent_pid)
            if parent is None:
                raise _deny()
            if binary == "system-wsl.exe":
                if parent_pid not in docker_services:
                    raise _deny()
            else:
                if (
                    parent.get("name") != "wsl.exe"
                    or _path(_string(parent.get("executable")))
                    != _path(BINARIES["system-wsl.exe"][0])
                    or infrastructure_arguments(
                        _string(parent.get("command")), BINARIES["system-wsl.exe"][0]
                    )
                    != args
                ):
                    raise _deny()
            launchers[pid] = (binary, kind)
            allowed.add(pid)
        vm_ids: set[str] = set()
        for pid, row in by_pid.items():
            if row.get("name") != "wslhost.exe":
                continue
            _signed(row, "wslhost.exe")
            args = infrastructure_arguments(_string(row.get("command")), BINARIES["wslhost.exe"][0])
            host_parent_pid = _integer(row.get("parent_pid"))
            if host_parent_pid in launchers and launchers[host_parent_pid][0] == "wsl.exe":
                fields = _flags(args, {"--distro-id", "--vm-id", "--handle", "--event", "--parent"})
                if _uuid(fields["--distro-id"]) != distro_id:
                    raise _deny()
                vm_ids.add(_uuid(fields["--vm-id"]))
                registered_hosts.append(pid)
                allowed.add(pid)
        if not registered_hosts or len(vm_ids) != 1:
            raise _deny()
        for pid, row in by_pid.items():
            name = row.get("name")
            if pid in allowed or name not in {"wslhost.exe", "wslrelay.exe"}:
                continue
            if _integer(row.get("parent_pid")) != service_pid:
                raise _deny()
            binary = _string(name)
            _signed(row, binary)
            args = infrastructure_arguments(_string(row.get("command")), BINARIES[binary][0])
            keys = {"--vm-id", "--handle"} | ({"--mode"} if name == "wslrelay.exe" else set())
            fields = _flags(args, keys)
            if _uuid(fields["--vm-id"]) not in vm_ids or (
                name == "wslrelay.exe" and fields["--mode"] != "1"
            ):
                raise _deny()
            allowed.add(pid)
        if allowed != set(by_pid):
            raise _deny()
        # Pin generations, relationship, binary and exact commands between passes.
        safe = [
            [
                pid,
                row.get("parent_pid"),
                row.get("created_at"),
                row.get("binary_sha256"),
                hashlib.sha256(str(row.get("command")).encode()).hexdigest(),
            ]
            for pid, row in sorted(by_pid.items())
        ]
        digest = hashlib.sha256(
            json.dumps([safe, service, distro_id], sort_keys=True).encode()
        ).hexdigest()
        return InfrastructureClassification(frozenset(allowed), frozenset(docker), digest)
    except LocalRecoveryRefusal:
        raise
    except Exception:
        raise _deny() from None
