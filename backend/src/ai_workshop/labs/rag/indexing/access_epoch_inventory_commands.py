"""Fixed private inventory reads; only the recorded runner proves execution.

This builder accepts no caller URL, method, credential, count body or response
authority. The retained source issuer owns the parent/deployment/key binding.
"""

import base64
import re
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    DecodedIndexMetadata,
    provenance_count_body,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import InventoryReadBinding
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE

_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
_CA = "/usr/share/elasticsearch/config/access-epoch-tls/http/ca.crt"
_ROUTES = {
    "listing": (
        "/_cluster/state/metadata?flat_settings=true&filter_path="
        "cluster_uuid,metadata.indices.*.state,metadata.indices.*.settings.*uuid,"
        "metadata.indices.*.settings.*hidden"
    ),
    "cluster_info": "/",
    "identity_state": (
        "/_cluster/state/master_node,nodes?filter_path=cluster_uuid,master_node,nodes"
    ),
    "cluster_state": (
        "/_cluster/state/metadata,routing_table?flat_settings=true&filter_path="
        "cluster_uuid,cluster_name,metadata.indices.*.state,metadata.indices.*.settings,"
        "metadata.indices.*.mappings,metadata.indices.*.aliases,metadata.indices.*.system,"
        "routing_table.indices"
    ),
    "nodes_info": (
        "/_nodes/jvm?filter_path=_nodes,cluster_name,nodes.*.name,nodes.*.ephemeral_id,"
        "nodes.*.roles,nodes.*.jvm.start_time_in_millis"
    ),
    "nodes_docs": (
        "/_nodes/stats/indices/docs?level=indices&filter_path=_nodes,cluster_name,"
        "nodes.*.indices.indices.*.docs"
    ),
}


class InventoryBindingIssuer(Protocol):
    def assert_issued(self, binding: InventoryReadBinding) -> object: ...


@dataclass(frozen=True, slots=True, eq=False)
class InventoryCommand:
    purpose: str
    index_name: str | None = field(repr=False)
    argv: tuple[str, ...]
    private_stdin: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class InventoryResponse:
    exit_code: int
    stdout: bytes = field(repr=False)


def _denied(response: bool = False) -> ValueError:
    return ValueError("inventory_response_denied" if response else "inventory_command_denied")


def _quote(value: str) -> str:
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise _denied()
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class InventoryCommands:
    def __init__(self, binding: InventoryReadBinding, issuer: InventoryBindingIssuer) -> None:
        self.binding, self.issuer = binding, issuer
        self._commands: dict[InventoryCommand, tuple[str, str | None, tuple[str, ...], bytes]] = {}
        try:
            self._guard()
        except Exception:
            raise _denied() from None

    def _guard(self) -> None:
        b = self.binding
        if (
            type(b) is not InventoryReadBinding
            or b.phase not in {"original", "bootstrap", "final"}
            or any(
                type(x) is not UUID or x.int == 0
                for x in (b.nonce, b.epoch_id, b.execution_id, b.parent_action_id)
            )
            or type(b.container_id) is not str
            or re.fullmatch(r"[0-9a-f]{64}", b.container_id) is None
            or type(b.permissions) is not AccessEpochPermissions
            or b.phase == "original"
            and b.collector_secret is not None
            or b.phase != "original"
            and type(b.collector_secret) is not SecretStr
        ):
            raise _denied()
        if self.issuer.assert_issued(b) is not None:
            raise _denied()
        if b.collector_secret is not None:
            encoded = b.collector_secret.get_secret_value()
            if not 1 <= len(encoded) <= 4096:
                raise _denied()
            raw = base64.b64decode(encoded, validate=True)
            identifier, secret = raw.decode("ascii").split(":", 1)
            if base64.b64encode(raw).decode("ascii") != encoded or any(
                re.fullmatch(r"[A-Za-z0-9_-]{1,256}", x) is None for x in (identifier, secret)
            ):
                raise _denied()

    def _index(self, name: str, method: str) -> None:
        if type(name) is not str or name in self.binding.permissions.aliases:
            raise _denied()
        self.binding.permissions.authorize("collector", method, (name,))

    def _command(
        self, purpose: str, name: str | None, route: str, body: bytes | None
    ) -> InventoryCommand:
        self._guard()
        scheme = "http" if self.binding.phase == "original" else "https"
        config = ['request = "GET"', "url = " + _quote(scheme + "://localhost:9200" + route)]
        if self.binding.collector_secret is not None:
            config.append(
                "header = "
                + _quote(
                    "Authorization: ApiKey " + self.binding.collector_secret.get_secret_value()
                )
            )
        if body is not None:
            config += [
                'header = "Content-Type: application/json"',
                "data = " + _quote(body.decode("utf-8")),
            ]
        private = ("\n".join(config) + "\n").encode("utf-8")
        if len(private) > 65536:
            raise _denied()
        argv: tuple[str, ...] = (
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
        )
        if scheme == "https":
            argv += ("--cacert", _CA)
        argv += (
            "--proto",
            "=" + scheme,
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
        )
        command = InventoryCommand(purpose, name, argv, private)
        self._commands[command] = (purpose, name, argv, private)
        return command

    def read_cluster(self, purpose: str) -> InventoryCommand:
        try:
            if type(purpose) is not str or purpose not in _ROUTES:
                raise _denied()
            return self._command(purpose, None, _ROUTES[purpose], None)
        except Exception:
            raise _denied() from None

    def read_index(self, name: str, purpose: str) -> InventoryCommand:
        try:
            self._guard()
            if purpose == "metadata":
                self._index(name, "get")
                route = "/" + name + "?flat_settings=true&include_defaults=true"
            elif purpose == "count":
                self._index(name, "count")
                route = "/" + name + "/_count"
            else:
                raise _denied()
            return self._command(purpose, name, route, None)
        except Exception:
            raise _denied() from None

    def read_provenance(self, metadata: DecodedIndexMetadata) -> InventoryCommand:
        try:
            self._guard()
            if type(metadata) is not DecodedIndexMetadata:
                raise _denied()
            self._index(metadata.name, "count")
            body = provenance_count_body(metadata).body
            return self._command(
                "provenance_count", metadata.name, "/" + metadata.name + "/_count", body
            )
        except Exception:
            raise _denied() from None

    def assert_issued(self, command: InventoryCommand) -> None:
        try:
            self._guard()
            if type(command) is not InventoryCommand or self._commands.get(command) != (
                command.purpose,
                command.index_name,
                command.argv,
                command.private_stdin,
            ):
                raise _denied()
        except Exception:
            raise _denied() from None

    def decode(self, command: InventoryCommand, response: InventoryResponse) -> bytes:
        try:
            self.assert_issued(command)
            del self._commands[command]
            if (
                type(response) is not InventoryResponse
                or type(response.exit_code) is not int
                or response.exit_code != 0
                or type(response.stdout) is not bytes
                or not 5 <= len(response.stdout) <= 262148
            ):
                raise _denied()
            body, status = response.stdout.rsplit(b"\n", 1)
            if not body or len(body) > 262144 or status != b"200":
                raise _denied()
            return body
        except Exception:
            raise _denied(True) from None
