"""Fixed, bounded HTTPS reads; packet data is not source or cutover authority.

The phase source supplies freshly guarded CA/credential material and checks it
again after this await. A worker owns connect/read/close. Cancellation waits for
its cleanup and never turns a timeout into evidence of successful cleanup.
"""

import asyncio
import base64
import io
import re
from collections.abc import Buffer
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from hashlib import sha256
from http.client import HTTPResponse, HTTPSConnection
from socket import AF_INET, SOCK_STREAM, socket
from ssl import CERT_REQUIRED, PROTOCOL_TLS_CLIENT, SSLContext, SSLSocket, TLSVersion
from threading import Event
from time import monotonic
from typing import cast
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing.access_epoch_auth_packets import finite_privilege_matrix
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json

_ROLES: tuple[ServiceRole, ...] = ("reader", "writer", "collector")
_TIMEOUT = 5.0
_HEADER_LIMIT = 65536
_REQUEST_LIMIT = 65536
_IDENTITY_LIMIT = 2 * 1024 * 1024
_AUTH_LIMIT = 262144
_ROUTES = (
    "/",
    "/_cluster/state/master_node,nodes",
    "/_nodes/settings,http,transport,remote_cluster_server,jvm?flat_settings=true",
)


def _denied() -> ValueError:
    return ValueError("secured_https_read_denied")


class _StoppedRead(BaseException):
    pass


@dataclass(frozen=True, slots=True)
class SecuredHttpsKey:
    """Ordinary protected-source input, without an issuance assertion."""

    role: ServiceRole
    key_id: str
    key_name: str
    encoded: SecretStr = field(repr=False)


@dataclass(frozen=True, slots=True)
class SecuredHttpsReadCatalog:
    epoch_id: UUID
    permissions: AccessEpochPermissions
    http_ca_pem: bytes = field(repr=False)
    http_leaf_sha256: str
    keys: tuple[SecuredHttpsKey, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SecuredHttpsResponse:
    body: bytes = field(repr=False)
    protocol: str
    leaf_der_sha256: str


def _request(
    catalog: SecuredHttpsReadCatalog, slot: int
) -> tuple[str, str, str, bytes | None, int]:
    if (
        type(catalog) is not SecuredHttpsReadCatalog
        or type(slot) is not int
        or not 0 <= slot <= 8
        or type(catalog.epoch_id) is not UUID
        or type(catalog.epoch_id.int) is not int
        or not 0 < catalog.epoch_id.int < 1 << 128
        or type(catalog.http_ca_pem) is not bytes
        or not 0 < len(catalog.http_ca_pem) <= 16384
        or type(catalog.http_leaf_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", catalog.http_leaf_sha256) is None
        or type(catalog.keys) is not tuple
        or len(catalog.keys) != 3
    ):
        raise _denied()
    catalog.http_ca_pem.decode("ascii", errors="strict")
    # This also validates exact prefix/namespace/role types for identity GETs.
    finite_privilege_matrix(catalog.epoch_id, catalog.permissions, "collector")
    roles: set[str] = set()
    ids: set[str] = set()
    secrets: set[bytes] = set()
    for key in catalog.keys:
        if (
            type(key) is not SecuredHttpsKey
            or type(key.role) is not str
            or key.role not in _ROLES
            or key.role in roles
            or type(key.key_id) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,256}", key.key_id) is None
            or key.key_id in ids
            or type(key.key_name) is not str
            or not 0 < len(key.key_name) <= 512
            or type(key.encoded) is not SecretStr
        ):
            raise _denied()
        encoded = key.encoded.get_secret_value()
        if not 0 < len(encoded) <= 4096:
            raise _denied()
        raw = base64.b64decode(encoded, validate=True)
        identifier, separator, secret = raw.partition(b":")
        if (
            base64.b64encode(raw).decode("ascii") != encoded
            or identifier != key.key_id.encode("ascii")
            or separator != b":"
            or re.fullmatch(rb"[A-Za-z0-9_-]{1,256}", secret) is None
            or secret in secrets
        ):
            raise _denied()
        roles.add(key.role)
        ids.add(key.key_id)
        secrets.add(secret)
    role = "collector" if slot < 3 else _ROLES[(slot - 3) // 2]
    key = next(key for key in catalog.keys if key.role == role)
    body = None
    method = "GET"
    route = _ROUTES[slot] if slot < 3 else "/_security/_authenticate"
    if slot in {4, 6, 8}:
        method, route = "POST", "/_security/user/_has_privileges"
        body = canonical_json(
            finite_privilege_matrix(catalog.epoch_id, catalog.permissions, role)[0]
        ).encode()
    authorization = "ApiKey " + key.encoded.get_secret_value()
    if len(body or b"") + len(authorization) + len(route) + 512 > _REQUEST_LIMIT:
        raise _denied()
    return method, route, authorization, body, _IDENTITY_LIMIT if slot < 3 else _AUTH_LIMIT


class _Budget:
    def __init__(self, stop: Event) -> None:
        self.stop, self.end = stop, monotonic() + _TIMEOUT

    def remaining(self) -> float:
        if self.stop.is_set():
            raise _StoppedRead()
        value = self.end - monotonic()
        if value <= 0:
            raise _denied()
        return min(value, _TIMEOUT)


class _BudgetReader(io.RawIOBase):
    def __init__(self, stream: io.RawIOBase, peer: SSLSocket, budget: _Budget) -> None:
        self.stream, self.peer, self.budget = stream, peer, budget
        self.header_pending, self.header_bytes = True, 0
        super().__init__()

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Buffer) -> int:
        self.peer.settimeout(self.budget.remaining())
        count = self.stream.readinto(buffer)
        self.budget.remaining()
        if type(count) is not int or count < 0:
            raise _denied()
        if self.header_pending:
            self.header_bytes += count
            if self.header_bytes > _HEADER_LIMIT:
                raise _denied()
        return count

    def close(self) -> None:
        try:
            self.stream.close()
        finally:
            super().close()


class _BudgetSocket:
    def __init__(self, peer: SSLSocket, budget: _Budget) -> None:
        self.peer, self.budget = peer, budget
        self.readers: list[_BudgetReader] = []

    def makefile(self, mode: str) -> io.BufferedReader:
        if mode != "rb":
            raise _denied()
        self.budget.remaining()
        # The real socket file retains its OS handle when HTTPConnection hands
        # a Connection: close response to HTTPResponse. Final cleanup closes both.
        stream = cast(io.RawIOBase, self.peer.makefile("rb", buffering=0))
        reader = _BudgetReader(stream, self.peer, self.budget)
        self.readers.append(reader)
        return io.BufferedReader(reader)

    def sendall(self, data: bytes) -> None:
        self.peer.settimeout(self.budget.remaining())
        self.peer.sendall(data)
        self.budget.remaining()

    def close(self) -> None:
        self.peer.close()


class _StrictResponse(HTTPResponse):
    """Retain stdlib body reads, but require complete bounded chunk framing.

    HTTPResponse otherwise discards two bytes without checking the delimiter,
    accepts non-HTTP integer syntax for sizes, and treats trailer EOF as success.
    """

    _framing_bytes = 0

    def _framing_line(self) -> bytes:
        if self.fp is None:
            raise _denied()
        line = self.fp.readline(8193)
        self._framing_bytes += len(line)
        if not line.endswith(b"\r\n") or len(line) > 8192 or self._framing_bytes > _HEADER_LIMIT:
            raise _denied()
        return line[:-2]

    def _read_next_chunk_size(self) -> int:
        line = self._framing_line()
        token = rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
        quoted = rb'"(?:[\t !#-\[\]-~]|\\[\t -~])*"'
        if (
            re.fullmatch(
                rb"[0-9A-Fa-f]{1,8}(?:;" + token + rb"(?:=(?:" + token + rb"|" + quoted + rb"))?)*",
                line,
            )
            is None
        ):
            raise _denied()
        size = int(line.partition(b";")[0], 16)
        if size > _IDENTITY_LIMIT:
            raise _denied()
        return size

    def _read_and_discard_trailer(self) -> None:
        while True:
            line = self._framing_line()
            if not line:
                return
            if re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+:[\t -~]*", line) is None:
                raise _denied()
            if line.partition(b":")[0].lower() in {
                b"content-length",
                b"transfer-encoding",
                b"content-encoding",
                b"trailer",
            }:
                raise _denied()

    def _get_chunk_left(self) -> int | None:
        chunk_left = self.chunk_left
        if not chunk_left:
            if chunk_left is not None and (self.fp is None or self.fp.read(2) != b"\r\n"):
                raise _denied()
            chunk_left = self._read_next_chunk_size()
            if chunk_left == 0:
                self._read_and_discard_trailer()
                self.close()
                chunk_left = None
            self.chunk_left = chunk_left
        return chunk_left


def _length(response: object, limit: int) -> int | None:
    # HTTPResponse has already parsed the wire. Inspect repeated headers before
    # reading the body rather than trusting the library's normalized length.
    if (
        not isinstance(response, HTTPResponse)
        or type(response.status) is not int
        or response.status != 200
    ):
        raise _denied()
    headers: dict[str, list[str]] = {}
    for name, value in response.getheaders():
        headers.setdefault(name.lower(), []).append(value)
    for name in ("content-encoding", "content-length", "transfer-encoding"):
        if len(headers.get(name, [])) > 1:
            raise _denied()
    if headers.get("content-encoding", ["identity"]) != ["identity"]:
        raise _denied()
    transfer = headers.get("transfer-encoding")
    length = headers.get("content-length")
    if transfer is not None and (transfer != ["chunked"] or length is not None):
        raise _denied()
    if length is None:
        return None
    if re.fullmatch(r"0|[1-9][0-9]{0,9}", length[0]) is None or int(length[0]) > limit:
        raise _denied()
    return int(length[0])


async def _capture_https_read(catalog: SecuredHttpsReadCatalog, slot: int) -> SecuredHttpsResponse:
    """One fixed read; its source owns nonce/slot replay and phase validation."""
    try:
        method, route, authorization, body, limit = _request(catalog, slot)
        ca, leaf = catalog.http_ca_pem.decode("ascii"), catalog.http_leaf_sha256
    except Exception:
        raise _denied() from None
    stop = Event()

    def worker() -> SecuredHttpsResponse:
        budget = _Budget(stop)
        raw: socket | None = None
        peer: SSLSocket | None = None
        guarded: _BudgetSocket | None = None
        connection: HTTPSConnection | None = None
        response = None
        result = None
        primary: BaseException | None = None
        cleanup_failed = False
        try:
            context = SSLContext(PROTOCOL_TLS_CLIENT)
            context.check_hostname = True
            context.verify_mode = CERT_REQUIRED
            context.minimum_version = TLSVersion.TLSv1_2
            context.set_alpn_protocols(["http/1.1"])
            context.load_verify_locations(cadata=ca)
            budget.remaining()
            raw = socket(AF_INET, SOCK_STREAM)
            raw.settimeout(budget.remaining())
            raw.connect(("127.0.0.1", 9200))
            budget.remaining()
            peer = context.wrap_socket(
                raw, server_hostname="127.0.0.1", do_handshake_on_connect=False
            )
            peer.settimeout(budget.remaining())
            peer.do_handshake()
            budget.remaining()
            actual_leaf = sha256(peer.getpeercert(binary_form=True) or b"").hexdigest()
            protocol = peer.version()
            if actual_leaf != leaf or protocol not in {"TLSv1.2", "TLSv1.3"}:
                raise _denied()
            guarded = _BudgetSocket(peer, budget)
            connection = HTTPSConnection(
                "127.0.0.1", 9200, context=context, timeout=budget.remaining()
            )
            connection.set_debuglevel(0)
            connection.response_class = _StrictResponse
            connection.sock = cast(SSLSocket, guarded)
            headers = {
                "Authorization": authorization,
                "Accept-Encoding": "identity",
                "Connection": "close",
            }
            if body is not None:
                headers["Content-Type"] = "application/json"
            connection.request(method, route, body=body, headers=headers)
            response = connection.getresponse()
            budget.remaining()
            length = _length(response, limit)
            for reader in guarded.readers:
                reader.header_pending = False
            chunks = bytearray()
            while True:
                budget.remaining()
                chunk = response.read1(min(16384, limit + 1 - len(chunks)))
                budget.remaining()
                if not chunk:
                    break
                chunks.extend(chunk)
                if len(chunks) > limit:
                    raise _denied()
            if not chunks or (length is not None and len(chunks) != length):
                raise _denied()
            result = SecuredHttpsResponse(bytes(chunks), protocol, actual_leaf)
        except BaseException as error:
            primary = error
        finally:
            # Also close files retained during an exception in getresponse().
            owned = [response, *(guarded.readers if guarded else []), connection, peer, raw]
            for resource in owned:
                if resource is not None:
                    try:
                        resource.close()
                    except BaseException:
                        cleanup_failed = True
        if primary is None and not cleanup_failed and result is not None:
            budget.remaining()
            return result
        if isinstance(primary, _StoppedRead):
            if cleanup_failed:
                primary.add_note("secured_https_cleanup_unverified")
            raise primary
        denial = _denied()
        if cleanup_failed:
            denial.add_note("secured_https_cleanup_unverified")
        if primary is not None and not isinstance(primary, Exception):
            if cleanup_failed:
                primary.add_note("secured_https_cleanup_unverified")
            raise primary
        raise denial from None

    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="secured-https")
    try:
        future = asyncio.get_running_loop().run_in_executor(executor, worker)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError as primary:
            stop.set()
            while not future.done():
                try:
                    await asyncio.shield(future)
                except asyncio.CancelledError:
                    continue
                except BaseException:
                    break
            if not future.cancelled():
                try:
                    future.result()
                except BaseException as error:
                    if "secured_https_cleanup_unverified" in getattr(error, "__notes__", ()):
                        primary.add_note("secured_https_cleanup_unverified")
            raise primary
    except Exception as error:
        denial = _denied()
        if "secured_https_cleanup_unverified" in getattr(error, "__notes__", ()):
            denial.add_note("secured_https_cleanup_unverified")
        raise denial from None
    finally:
        executor.shutdown(wait=True)
