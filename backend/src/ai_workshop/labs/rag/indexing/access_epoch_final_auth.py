"""Fixed final-server role checks; no executor, factory or settlement authority.

The retained issuer binds exact issued descriptors and protected credentials.
Finite privilege probes do not establish absence of every arbitrary outside grant.
"""

import base64
import json
import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Protocol
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapIssuedKey
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE

_ROLES: tuple[ServiceRole, ...] = ("reader", "writer", "collector")
_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
_CA = "/usr/share/elasticsearch/config/access-epoch-tls/http/ca.crt"
_CLUSTER_DENIED = ("all", "manage", "manage_security", "manage_api_key", "manage_own_api_key")
_MUTATIONS = (
    "write",
    "manage",
    "delete",
    "delete_index",
    "create_index",
    "index",
    "create",
    "create_doc",
    "maintenance",
)


@dataclass(frozen=True, slots=True, eq=False)
class FinalAuthBinding:
    nonce: UUID
    epoch_id: UUID
    execution_id: UUID
    container_id: str
    permissions: AccessEpochPermissions
    keys: tuple[BootstrapIssuedKey, ...] = field(repr=False)


class FinalAuthBindingIssuer(Protocol):
    """Root validates current ledger, protected secrets, final daemon/TLS and scope."""

    def assert_issued(self, binding: FinalAuthBinding) -> None: ...


@dataclass(frozen=True, slots=True, eq=False)
class FinalAuthCommand:
    role: ServiceRole
    purpose: str
    argv: tuple[str, ...]
    private_stdin: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class FinalAuthResponse:
    """Private captured wire data; constructing it does not prove native execution."""

    exit_code: int
    stdout: bytes = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class AuthenticatedFinalKey:
    role: ServiceRole
    key_id: str


@dataclass(frozen=True, slots=True, eq=False)
class FinalRoleCheck:
    role: ServiceRole
    key_id: str


@dataclass(frozen=True, slots=True, eq=False)
class FinalAuthObservation:
    epoch_id: UUID
    execution_id: UUID
    container_id: str
    manifest_json: str


def _denied(response: bool = False) -> ValueError:
    return ValueError("final_auth_response_denied" if response else "final_auth_denied")


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _constant(value: str) -> None:
    raise ValueError


def _response(value: FinalAuthResponse) -> dict[str, Any]:
    if (
        type(value) is not FinalAuthResponse
        or type(value.exit_code) is not int
        or value.exit_code != 0
        or type(value.stdout) is not bytes
        or not 0 < len(value.stdout) <= 262144
    ):
        raise ValueError
    body, status = value.stdout.rsplit(b"\n", 1)
    if status != b"200":
        raise ValueError
    decoded = json.loads(
        body.decode("utf-8", errors="strict"), object_pairs_hook=_object, parse_constant=_constant
    )
    if type(decoded) is not dict:
        raise ValueError
    return decoded


def _quote(value: str) -> str:
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class FinalAuthCommands:
    def __init__(self, binding: FinalAuthBinding, issuer: FinalAuthBindingIssuer) -> None:
        self.binding, self.issuer = binding, issuer
        self._commands: set[FinalAuthCommand] = set()
        self._decoded: set[FinalAuthCommand] = set()
        self._authenticated: set[AuthenticatedFinalKey] = set()
        self._checks: set[FinalRoleCheck] = set()
        self._observed: set[FinalAuthObservation] = set()
        try:
            self._guard()
        except Exception:
            raise _denied() from None

    def _guard(self) -> None:
        b = self.binding
        if (
            type(b) is not FinalAuthBinding
            or any(type(x) is not UUID or x.int == 0 for x in (b.nonce, b.epoch_id, b.execution_id))
            or type(b.container_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", b.container_id) is None
            or type(b.permissions) is not AccessEpochPermissions
            or type(b.keys) is not tuple
            or len(b.keys) != 3
        ):
            raise ValueError
        self.issuer.assert_issued(b)
        ids: set[str] = set()
        roles: set[str] = set()
        issuances: set[UUID] = set()
        secrets: set[str] = set()
        for key in b.keys:
            if (
                type(key) is not BootstrapIssuedKey
                or type(key.role) is not str
                or key.role not in _ROLES
                or key.role in roles
                or type(key.key_id) is not str
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key.key_id) is None
                or key.key_id in ids
                or type(key.epoch_id) is not UUID
                or key.epoch_id != b.epoch_id
                or type(key.issuance_id) is not UUID
                or key.issuance_id.int == 0
                or key.issuance_id in issuances
                or key.name != f"ai-workshop-{b.epoch_id}-{key.role}-{key.issuance_id}"
                or type(key.encoded) is not SecretStr
            ):
                raise ValueError
            encoded = key.encoded.get_secret_value()
            if not 1 <= len(encoded) <= 4096:
                raise ValueError
            raw = base64.b64decode(encoded, validate=True)
            if base64.b64encode(raw).decode("ascii") != encoded:
                raise ValueError
            identifier, secret = raw.decode("ascii").split(":", 1)
            if (
                identifier != key.key_id
                or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret) is None
                or secret in secrets
            ):
                raise ValueError
            b.permissions.descriptor(key.role)
            ids.add(key.key_id)
            roles.add(key.role)
            issuances.add(key.issuance_id)
            secrets.add(secret)

    def _key(self, role: ServiceRole) -> BootstrapIssuedKey:
        if type(role) is not str or role not in _ROLES:
            raise ValueError
        return next(key for key in self.binding.keys if key.role == role)

    def _matrix(self, role: ServiceRole) -> tuple[dict[str, object], dict[str, Any]]:
        descriptor = self.binding.permissions.descriptor(role)
        index = descriptor["indices"][0]
        names, required = index["names"], index["privileges"]
        outside = "access-epoch-outside-" + self.binding.epoch_id.hex
        if any(fnmatchcase(outside, name) for name in names):
            raise ValueError
        denied = ("all",) if role == "writer" else ("all", *_MUTATIONS)
        privileges = sorted(set(required) | set(denied))
        outside_privileges = sorted({"all", "read", "view_index_metadata", *_MUTATIONS})
        # Explicit names include restricted indices even with the default false flag.
        # A wildcard .security* would instead exclude restricted indices from the check.
        outside_names = ["*", ".security", outside]
        query: dict[str, object] = {
            "cluster": sorted(set(descriptor["cluster"]) | set(_CLUSTER_DENIED)),
            "index": [
                {"names": names, "privileges": privileges, "allow_restricted_indices": False},
                {
                    "names": outside_names,
                    "privileges": outside_privileges,
                    "allow_restricted_indices": False,
                },
            ],
            "application": [],
        }
        expected = {
            "username": "elastic",
            "has_all_requested": False,
            "cluster": {
                name: name in descriptor["cluster"]
                for name in sorted(set(descriptor["cluster"]) | set(_CLUSTER_DENIED))
            },
            "index": {
                **{name: {p: p in required for p in privileges} for name in names},
                **{name: {p: False for p in outside_privileges} for name in outside_names},
            },
            "application": {},
        }
        return query, expected

    def _command(self, role: ServiceRole, purpose: str) -> FinalAuthCommand:
        self._guard()
        key = self._key(role)
        if purpose == "authenticate":
            method, route, body = "GET", "/_security/_authenticate", None
        elif purpose == "privileges":
            method, route, body = "POST", "/_security/user/_has_privileges", self._matrix(role)[0]
        else:
            raise ValueError
        config = [
            "header = " + _quote("Authorization: ApiKey " + key.encoded.get_secret_value()),
            "request = " + _quote(method),
            "url = " + _quote("https://localhost:9200" + route),
        ]
        if body is not None:
            config.extend(
                [
                    'header = "Content-Type: application/json"',
                    "data = " + _quote(canonical_json(body)),
                ]
            )
        private = ("\n".join(config) + "\n").encode()
        if len(private) > 65536:
            raise ValueError
        command = FinalAuthCommand(
            role,
            purpose,
            (
                DOCKER_EXE,
                "--host",
                _PIPE,
                "exec",
                "-i",
                "--user",
                "elasticsearch",
                self.binding.container_id,
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
        self._commands.add(command)
        return command

    def authenticate(self, role: ServiceRole) -> FinalAuthCommand:
        try:
            return self._command(role, "authenticate")
        except Exception:
            raise _denied() from None

    def privileges(self, authenticated: AuthenticatedFinalKey) -> FinalAuthCommand:
        try:
            self._guard()
            if (
                type(authenticated) is not AuthenticatedFinalKey
                or authenticated not in self._authenticated
            ):
                raise ValueError
            return self._command(authenticated.role, "privileges")
        except Exception:
            raise _denied() from None

    def assert_command(self, command: FinalAuthCommand) -> None:
        try:
            self._guard()
            if (
                type(command) is not FinalAuthCommand
                or command not in self._commands
                or command in self._decoded
            ):
                raise ValueError
        except Exception:
            raise _denied() from None

    def _consume(self, command: FinalAuthCommand, purpose: str) -> None:
        self.assert_command(command)
        if command.purpose != purpose:
            raise ValueError
        self._decoded.add(command)

    def decode_authenticated(
        self, command: FinalAuthCommand, response: FinalAuthResponse
    ) -> AuthenticatedFinalKey:
        try:
            self._consume(command, "authenticate")
            value = _response(response)
            key = self._key(command.role)
            if (
                set(value)
                != {
                    "username",
                    "roles",
                    "full_name",
                    "email",
                    "metadata",
                    "enabled",
                    "authentication_realm",
                    "lookup_realm",
                    "authentication_type",
                    "api_key",
                }
                or value["username"] != "elastic"
                or value["enabled"] is not True
                or value["authentication_type"] != "api_key"
                or type(value["roles"]) is not list
                or any(type(role) is not str for role in value["roles"])
                or len(value["roles"]) != len(set(value["roles"]))
                or type(value["metadata"]) is not dict
                or any(
                    value[name] is not None and type(value[name]) is not str
                    for name in ("full_name", "email")
                )
                or value["api_key"]
                != {"id": key.key_id, "name": key.name, "managed_by": "elasticsearch"}
            ):
                raise ValueError
            realm = value["authentication_realm"]
            if (
                type(realm) is not dict
                or set(realm) != {"name", "type"}
                or any(type(x) is not str or not x for x in realm.values())
                or realm != value["lookup_realm"]
            ):
                raise ValueError
            result = AuthenticatedFinalKey(command.role, key.key_id)
            self._guard()
            self._authenticated.add(result)
            return result
        except Exception:
            raise _denied(True) from None

    def decode_privileges(
        self, command: FinalAuthCommand, response: FinalAuthResponse
    ) -> FinalRoleCheck:
        try:
            self._consume(command, "privileges")
            value = _response(response)
            # Canonical JSON equality preserves exact booleans versus 0/1 and floats.
            if canonical_json(value) != canonical_json(self._matrix(command.role)[1]):
                raise ValueError
            self._guard()
            result = FinalRoleCheck(command.role, self._key(command.role).key_id)
            self._checks.add(result)
            return result
        except Exception:
            raise _denied(True) from None

    def complete(self, checks: tuple[FinalRoleCheck, ...]) -> FinalAuthObservation:
        try:
            self._guard()
            if (
                type(checks) is not tuple
                or len(checks) != 3
                or any(type(x) is not FinalRoleCheck or x not in self._checks for x in checks)
                or {x.role for x in checks} != set(_ROLES)
            ):
                raise ValueError
            manifest = canonical_json(
                {
                    "schema_version": 1,
                    "epoch_id": str(self.binding.epoch_id),
                    "execution_id": str(self.binding.execution_id),
                    "container_id": self.binding.container_id,
                    "keys": {x.role: x.key_id for x in checks},
                    "auth_policy": {
                        "verification": (
                            "finite_privilege_checks_with_issuer_bound_exact_descriptors"
                        ),
                        "authentication_type": "api_key",
                        "namespace_patterns": self.binding.permissions.descriptor("writer")[
                            "indices"
                        ][0]["names"],
                        "descriptors": {
                            role: self.binding.permissions.descriptor(role) for role in _ROLES
                        },
                        "checked_privileges": {role: self._matrix(role)[0] for role in _ROLES},
                        "writer_manage_includes_index_delete": True,
                        "writer_write_includes_document_delete": True,
                    },
                }
            )
            result = FinalAuthObservation(
                self.binding.epoch_id,
                self.binding.execution_id,
                self.binding.container_id,
                manifest,
            )
            self._observed.add(result)
            return result
        except Exception:
            raise _denied() from None

    def assert_observed(self, observation: FinalAuthObservation) -> None:
        try:
            self._guard()
            if type(observation) is not FinalAuthObservation or observation not in self._observed:
                raise ValueError
        except Exception:
            raise _denied() from None
