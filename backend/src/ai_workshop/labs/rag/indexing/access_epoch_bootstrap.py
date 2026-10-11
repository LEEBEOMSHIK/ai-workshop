"""Fixed private bootstrap grammar, not an executor or proof of authorization.

Only the verified original-security-absent path is supported. Native execution,
durable outcomes, temporary file-user cleanup and daemon settlement are external.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE

_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
_URL = "https://localhost:9200"
_CA = "/usr/share/elasticsearch/config/access-epoch-tls/http/ca.crt"
_BUILTINS = {
    "elastic": {"superuser"},
    "kibana": {"kibana_system"},
    "kibana_system": {"kibana_system"},
    "logstash_system": {"logstash_system"},
    "beats_system": {"beats_system"},
    "apm_system": {"apm_system"},
    "remote_monitoring_user": {"remote_monitoring_agent", "remote_monitoring_collector"},
}


class BootstrapError(ValueError):
    """Finite codes only; raw credentials/responses never enter error messages."""


@dataclass(frozen=True, slots=True)
class BootstrapBinding:
    docker_executable: str
    docker_endpoint: str
    container_id: str
    epoch_id: UUID
    execution_id: UUID
    original_security_absent: bool


@dataclass(frozen=True, slots=True, eq=False)
class BootstrapCommand:
    argv: tuple[str, ...]
    private_stdin: bytes = field(repr=False)
    issuance_id: UUID | None = None
    key_name: str | None = None
    role: ServiceRole | None = None


@dataclass(frozen=True, slots=True, eq=False)
class BootstrapIssuedKey:
    key_id: str
    name: str
    epoch_id: UUID
    issuance_id: UUID
    role: ServiceRole
    encoded: SecretStr = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class BootstrapKeyObservation:
    """Exact public match only; contains no credential and proves no local settlement."""

    key_id: str
    name: str
    epoch_id: UUID
    issuance_id: UUID
    role: ServiceRole
    invalidated: bool
    creation_ms: int
    expiration_ms: int | None


def _quote(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _password(value: SecretStr) -> str:
    if type(value) is not SecretStr:
        raise ValueError
    plain = value.get_secret_value()
    if re.fullmatch(r"[!-~]{8,128}", plain) is None:
        raise ValueError
    return plain


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, value in pairs:
        if name in result:
            raise ValueError
        result[name] = value
    return result


def _constant(value: str) -> None:
    raise ValueError


def _response(exit_code: int, stdout: bytes) -> dict[str, Any]:
    if (
        type(exit_code) is not int
        or exit_code != 0
        or type(stdout) is not bytes
        or len(stdout) > 262144
    ):
        raise ValueError
    body, status = stdout.rsplit(b"\n", 1)
    if status != b"200":
        raise ValueError
    value = json.loads(
        body.decode("utf-8", errors="strict"), object_pairs_hook=_object, parse_constant=_constant
    )
    if type(value) is not dict:
        raise ValueError
    return value


def _user(name: str, value: object) -> None:
    if name not in _BUILTINS or type(value) is not dict:
        raise ValueError
    if set(value) != {"username", "roles", "full_name", "email", "metadata", "enabled"}:
        raise ValueError
    roles, metadata = value["roles"], value["metadata"]
    if (
        value["username"] != name
        or type(value["enabled"]) is not bool
        or (name == "elastic" and value["enabled"] is not True)
        or value["full_name"] is not None
        or value["email"] is not None
        or type(roles) is not list
        or any(type(role) is not str for role in roles)
        or len(roles) != len(set(roles))
        or set(roles) != _BUILTINS[name]
        or type(metadata) is not dict
        or metadata.get("_reserved") is not True
        or not set(metadata) <= {"_reserved", "_deprecated", "_deprecated_reason"}
        or ("_deprecated" in metadata and type(metadata["_deprecated"]) is not bool)
        or ("_deprecated_reason" in metadata and type(metadata["_deprecated_reason"]) is not str)
    ):
        raise ValueError


class BootstrapCommands:
    def __init__(self, binding: BootstrapBinding, permissions: AccessEpochPermissions) -> None:
        try:
            if (
                type(binding) is not BootstrapBinding
                or type(permissions) is not AccessEpochPermissions
                or binding.docker_executable != DOCKER_EXE
                or binding.docker_endpoint != _PIPE
                or type(binding.container_id) is not str
                or re.fullmatch(r"[0-9a-f]{64}", binding.container_id) is None
                or type(binding.epoch_id) is not UUID
                or binding.epoch_id.int == 0
                or type(binding.execution_id) is not UUID
                or binding.execution_id.int == 0
                or binding.original_security_absent is not True
            ):
                raise ValueError
            self.binding, self._permissions = binding, permissions
            self._reset_prepared = False
            self._reset_command: BootstrapCommand | None = None
            self._issued: dict[UUID, BootstrapCommand] = {}
            self._decoded: set[UUID] = set()
            self._lookups: set[BootstrapCommand] = set()
            self._observations: set[BootstrapKeyObservation] = set()
            self._invalidations: dict[BootstrapCommand, str] = {}
            self._invalidation_ids: set[str] = set()
            self._audits: dict[BootstrapCommand, str] = {}
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    @property
    def permissions(self) -> AccessEpochPermissions:
        return self._permissions

    def _prefix(self) -> tuple[str, ...]:
        return (
            DOCKER_EXE,
            "--host",
            _PIPE,
            "exec",
            "-i",
            "--user",
            "elasticsearch",
            self.binding.container_id,
        )

    def reset_password(self) -> BootstrapCommand:
        try:
            if self._reset_prepared:
                raise ValueError
            self._reset_prepared = True
            argv = (
                *self._prefix(),
                "/usr/share/elasticsearch/bin/elasticsearch-reset-password",
                "--auto",
                "--batch",
                "--silent",
                "--username",
                "elastic",
                "--url",
                _URL,
            )
            self._reset_command = BootstrapCommand(argv, b"")
            return self._reset_command
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    def assert_reset_command(self, command: BootstrapCommand) -> None:
        if type(command) is not BootstrapCommand or command is not self._reset_command:
            raise BootstrapError("bootstrap_command_denied")

    def decode_reset(self, command: BootstrapCommand, exit_code: int, stdout: bytes) -> SecretStr:
        """Decode protected CLI capture only; never synthesize a replacement password."""
        try:
            if type(command) is not BootstrapCommand or command is not self._reset_command:
                raise ValueError
            self._reset_command = None  # Unknown capture consumes the attempt too.
            if type(exit_code) is not int or exit_code != 0 or type(stdout) is not bytes:
                raise ValueError
            if len(stdout) > 130:
                raise ValueError
            line = (
                stdout.removesuffix(b"\r\n")
                if stdout.endswith(b"\r\n")
                else stdout.removesuffix(b"\n")
            )
            password = SecretStr(line.decode("ascii", errors="strict"))
            _password(password)
            return password
        except Exception:
            raise BootstrapError("bootstrap_response_unknown") from None

    def _curl(
        self, password: SecretStr, method: str, route: str, body: dict[str, Any] | None = None
    ) -> BootstrapCommand:
        try:
            # Private implementation only; public methods select exact routes and payloads.
            lookup = (
                method == "GET"
                and re.fullmatch(
                    rf"/_security/api_key\?name=ai-workshop-{self.binding.epoch_id}"
                    r"-(reader|writer|collector)-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",
                    route,
                )
                is not None
            )
            if not lookup and (method, route) not in {
                ("GET", "/_security/_authenticate"),
                ("GET", "/_security/user"),
                ("GET", "/_security/api_key"),
                ("POST", "/_security/api_key"),
                ("DELETE", "/_security/api_key"),
            }:
                raise ValueError
            config = [
                f"user = {_quote('elastic:' + _password(password))}",
                f"request = {_quote(method)}",
                f"url = {_quote(_URL + route)}",
            ]
            if body is not None:
                config.extend(
                    [
                        'header = "Content-Type: application/json"',
                        "data = " + _quote(json.dumps(body, sort_keys=True, separators=(",", ":"))),
                    ]
                )
            private = ("\n".join(config) + "\n").encode("utf-8")
            if len(private) > 65536:
                raise ValueError
            return BootstrapCommand(
                (
                    *self._prefix(),
                    "/usr/bin/curl",
                    "-q",
                    "--config",
                    "-",
                    "--cacert",
                    _CA,
                    "--proto",
                    "=https",
                    "--noproxy",
                    "*",
                    "--connect-timeout",
                    "5",
                    "--max-time",
                    "20",
                    "--silent",
                    "--show-error",
                    "--fail-with-body",
                    "--write-out",
                    "\n%{http_code}",
                ),
                private,
            )
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    def authenticate(self, password: SecretStr) -> BootstrapCommand:
        return self._curl(password, "GET", "/_security/_authenticate")

    def audit_command(self, password: SecretStr, purpose: str) -> BootstrapCommand:
        try:
            if purpose in {"file_users", "file_roles"}:
                filename = "users" if purpose == "file_users" else "users_roles"
                command = BootstrapCommand(
                    (
                        *self._prefix(),
                        "/usr/bin/cat",
                        "/usr/share/elasticsearch/config/" + filename,
                    ),
                    b"",
                )
            elif purpose == "authenticate":
                command = self.authenticate(password)
            elif purpose == "users":
                command = self.audit_users(password)
            elif purpose == "api_keys":
                command = self.audit_api_keys(password)
            else:
                raise ValueError
            self._audits[command] = purpose
            return command
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    def assert_audit_command(self, command: BootstrapCommand, purpose: str) -> None:
        if type(command) is not BootstrapCommand or self._audits.get(command) != purpose:
            raise BootstrapError("bootstrap_command_denied")

    @staticmethod
    def decode_file_realm_empty(exit_code: int, stdout: bytes) -> None:
        if (
            type(exit_code) is not int
            or exit_code != 0
            or type(stdout) is not bytes
            or len(stdout) > 65536
            or any(
                line.strip() and not line.lstrip().startswith(b"#") for line in stdout.splitlines()
            )
        ):
            raise BootstrapError("bootstrap_response_unknown")

    def permissions_descriptor(self, role: ServiceRole) -> dict[str, Any]:
        """A fresh public descriptor for the durable child reservation fingerprint."""
        return dict(self._permissions.descriptor(role))

    def assert_role_command(self, command: BootstrapCommand, mutation: str | None) -> None:
        """Exact builder objects only; mutations still need a separate committed permit."""
        try:
            if type(command) is not BootstrapCommand:
                raise ValueError
            if mutation is None:
                if command not in self._lookups:
                    raise ValueError
            elif mutation == "issue":
                if (
                    command.issuance_id is None
                    or self._issued.get(command.issuance_id) is not command
                    or command.issuance_id in self._decoded
                ):
                    raise ValueError
            elif mutation == "invalidate":
                if command not in self._invalidations:
                    raise ValueError
            else:
                raise ValueError
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    def audit_users(self, password: SecretStr) -> BootstrapCommand:
        return self._curl(password, "GET", "/_security/user")

    def audit_api_keys(self, password: SecretStr) -> BootstrapCommand:
        return self._curl(password, "GET", "/_security/api_key")

    def issue_key(
        self, password: SecretStr, role: ServiceRole, issuance_id: UUID
    ) -> BootstrapCommand:
        try:
            if type(issuance_id) is not UUID or issuance_id.int == 0 or issuance_id in self._issued:
                raise ValueError
            descriptor = self._permissions.descriptor(role)
            name = f"ai-workshop-{self.binding.epoch_id}-{role}-{issuance_id}"
            command = self._curl(
                password,
                "POST",
                "/_security/api_key",
                {
                    "name": name,
                    "role_descriptors": {role: descriptor},
                    "metadata": {
                        "ai_workshop_epoch": str(self.binding.epoch_id),
                        "ai_workshop_role": role,
                        "ai_workshop_issuance": str(issuance_id),
                    },
                },
            )
            issued = BootstrapCommand(command.argv, command.private_stdin, issuance_id, name, role)
            self._issued[issuance_id] = issued  # Never rebuild after a potentially lost submission.
            return issued
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    def decode_issued(
        self, command: BootstrapCommand, exit_code: int, stdout: bytes
    ) -> BootstrapIssuedKey:
        try:
            if (
                type(command) is not BootstrapCommand
                or command.issuance_id is None
                or self._issued.get(command.issuance_id) is not command
                or command.issuance_id in self._decoded
                or command.role is None
            ):
                raise ValueError
            self._decoded.add(command.issuance_id)
            value = _response(exit_code, stdout)
            required = {"id", "name", "api_key", "encoded"}
            if not required <= set(value) or not set(value) <= required | {"expiration", "type"}:
                raise ValueError
            if any(type(value[key]) is not str for key in required):
                raise ValueError
            if (
                value["name"] != command.key_name
                or value.get("type", "rest") != "rest"
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value["id"]) is None
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value["api_key"]) is None
                or (
                    "expiration" in value
                    and (type(value["expiration"]) is not int or value["expiration"] <= 0)
                )
            ):
                raise ValueError
            expected = base64.b64encode(f"{value['id']}:{value['api_key']}".encode("ascii")).decode(
                "ascii"
            )
            if value["encoded"] != expected:
                raise ValueError
            return BootstrapIssuedKey(
                value["id"],
                value["name"],
                self.binding.epoch_id,
                command.issuance_id,
                command.role,
                SecretStr(expected),
            )
        except Exception:
            raise BootstrapError("bootstrap_response_unknown") from None

    def lookup_key(
        self, password: SecretStr, role: ServiceRole, issuance_id: UUID
    ) -> BootstrapCommand:
        try:
            if type(issuance_id) is not UUID or issuance_id.int == 0:
                raise ValueError
            self._permissions.descriptor(role)
            name = f"ai-workshop-{self.binding.epoch_id}-{role}-{issuance_id}"
            raw = self._curl(password, "GET", f"/_security/api_key?name={name}")
            command = BootstrapCommand(raw.argv, raw.private_stdin, issuance_id, name, role)
            self._lookups.add(command)
            return command
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    def decode_lookup(
        self, command: BootstrapCommand, exit_code: int, stdout: bytes
    ) -> BootstrapKeyObservation | None:
        """None means an empty authorized HTTP200 result, never successful issuance."""
        try:
            if (
                type(command) is not BootstrapCommand
                or command not in self._lookups
                or command.issuance_id is None
                or command.role is None
                or command.key_name is None
            ):
                raise ValueError
            self._lookups.remove(command)
            response = _response(exit_code, stdout)
            if set(response) != {"api_keys"} or type(response["api_keys"]) is not list:
                raise ValueError
            matches = response["api_keys"]
            if not matches:
                return None
            if len(matches) != 1 or type(matches[0]) is not dict:
                raise ValueError
            value = matches[0]
            required = {
                "id",
                "name",
                "type",
                "creation",
                "invalidated",
                "username",
                "realm",
                "metadata",
                "role_descriptors",
            }
            if not required <= set(value) or not set(value) <= required | {
                "realm_type",
                "expiration",
                "invalidation",
            }:
                raise ValueError
            if (
                type(value["id"]) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", value["id"]) is None
                or value["name"] != command.key_name
                or value["type"] != "rest"
                or value["username"] != "elastic"
                or value["realm"] != "reserved"
                or value.get("realm_type", "reserved") != "reserved"
                or type(value["creation"]) is not int
                or value["creation"] <= 0
                or type(value["invalidated"]) is not bool
                or (
                    "expiration" in value
                    and (
                        type(value["expiration"]) is not int
                        or value["expiration"] <= value["creation"]
                    )
                )
                or (
                    "invalidation" in value
                    and (
                        type(value["invalidation"]) is not int
                        or value["invalidation"] < value["creation"]
                        or not value["invalidated"]
                    )
                )
                or value["metadata"]
                != {
                    "ai_workshop_epoch": str(self.binding.epoch_id),
                    "ai_workshop_role": command.role,
                    "ai_workshop_issuance": str(command.issuance_id),
                }
            ):
                raise ValueError
            descriptors = value["role_descriptors"]
            if type(descriptors) is not dict or set(descriptors) != {command.role}:
                raise ValueError
            if type(descriptors[command.role]) is not dict:
                raise ValueError
            descriptor = dict(descriptors[command.role])
            if "transient_metadata" in descriptor:
                transient = descriptor.pop("transient_metadata")
                if (
                    type(transient) is not dict
                    or set(transient) != {"enabled"}
                    or transient["enabled"] is not True
                ):
                    raise ValueError
            expected = self._permissions.descriptor(command.role)
            # Canonical text equality preserves JSON bool-vs-int distinctions.
            if json.dumps(descriptor, sort_keys=True) != json.dumps(expected, sort_keys=True):
                raise ValueError
            observed = BootstrapKeyObservation(
                value["id"],
                command.key_name,
                self.binding.epoch_id,
                command.issuance_id,
                command.role,
                value["invalidated"],
                value["creation"],
                value.get("expiration"),
            )
            self._observations.add(observed)
            return observed
        except Exception:
            raise BootstrapError("bootstrap_response_unknown") from None

    def invalidate_key(
        self, password: SecretStr, observed: BootstrapKeyObservation
    ) -> BootstrapCommand:
        try:
            if (
                type(observed) is not BootstrapKeyObservation
                or observed not in self._observations
                or observed.invalidated
                or observed.key_id in self._invalidation_ids
            ):
                raise ValueError
            raw = self._curl(password, "DELETE", "/_security/api_key", {"ids": [observed.key_id]})
            command = BootstrapCommand(
                raw.argv, raw.private_stdin, observed.issuance_id, observed.name, observed.role
            )
            self._invalidation_ids.add(observed.key_id)
            self._invalidations[command] = observed.key_id
            return command
        except Exception:
            raise BootstrapError("bootstrap_command_denied") from None

    def decode_invalidated(self, command: BootstrapCommand, exit_code: int, stdout: bytes) -> str:
        try:
            if type(command) is not BootstrapCommand or command not in self._invalidations:
                raise ValueError
            key_id = self._invalidations.pop(command)  # Consume unknown ACK, never retry DELETE.
            value = _response(exit_code, stdout)
            required = {"invalidated_api_keys", "previously_invalidated_api_keys", "error_count"}
            if (
                not required <= set(value)
                or not set(value) <= required | {"error_details"}
                or type(value["error_count"]) is not int
                or value["error_count"] != 0
                or value.get("error_details", []) != []
            ):
                raise ValueError
            current, previous = (
                value["invalidated_api_keys"],
                value["previously_invalidated_api_keys"],
            )
            if (
                type(current) is not list
                or type(previous) is not list
                or current + previous != [key_id]
            ):
                raise ValueError
            return key_id
        except Exception:
            raise BootstrapError("bootstrap_response_unknown") from None

    @staticmethod
    def decode_api_keys(exit_code: int, stdout: bytes) -> None:
        try:
            if _response(exit_code, stdout) != {"api_keys": []}:
                raise ValueError
        except Exception:
            raise BootstrapError("bootstrap_response_unknown") from None

    @staticmethod
    def decode_users(exit_code: int, stdout: bytes) -> tuple[str, ...]:
        try:
            users = _response(exit_code, stdout)
            if "elastic" not in users:
                raise ValueError
            for name, value in users.items():
                _user(name, value)
            return tuple(sorted(users))
        except Exception:
            raise BootstrapError("bootstrap_response_unknown") from None

    @staticmethod
    def decode_authenticated(exit_code: int, stdout: bytes) -> None:
        try:
            value = _response(exit_code, stdout)
            extras = {"authentication_type", "authentication_realm", "lookup_realm"}
            if not extras <= set(value) or value["authentication_type"] != "realm":
                raise ValueError
            for name in ("authentication_realm", "lookup_realm"):
                if value[name] != {"name": "reserved", "type": "reserved"}:
                    raise ValueError
            _user("elastic", {key: item for key, item in value.items() if key not in extras})
        except Exception:
            raise BootstrapError("bootstrap_response_unknown") from None
