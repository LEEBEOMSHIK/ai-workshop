"""Actual HTTP framing with synthetic socket/TLS peers; no network is opened."""

import asyncio
import base64
import importlib
import importlib.util
import io
import json
import ssl
import threading
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions

LEAF = b"synthetic-server-leaf"
CA = b"synthetic-public-ca"
ROLES = ("reader", "writer", "collector")


def module():
    name = "ai_workshop.labs.rag.indexing.access_epoch_https_read"
    assert importlib.util.find_spec(name) is not None, "fixed HTTPS reader is not implemented"
    return importlib.import_module(name)


def test_fixed_reader_is_available():
    assert callable(module()._capture_https_read)


@pytest.mark.parametrize(
    "framing",
    [
        b"2\r\n{}XX0\r\n\r\n",  # chunk data delimiter is mandatory
        b"2\r\n{}\r\n0\r\n",  # EOF is not the final empty trailer line
        b"2\n{}\r\n0\r\n\r\n",  # size line must use CRLF
        b"+2\r\n{}\r\n0\r\n\r\n",
        b" 2\r\n{}\r\n0\r\n\r\n",
        b"2 \r\n{}\r\n0\r\n\r\n",
        b"2\r\n{}\r\n0\r\nX-Private: hidden\r\n",  # truncated trailers
    ],
)
async def test_malformed_chunk_framing_is_not_accepted(case, framing):
    case.peer.respond(framing, headers=[("Transfer-Encoding", "chunked")])
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await case.m._capture_https_read(case.catalog, 0)


async def test_complete_chunked_body_with_bounded_trailer(case):
    case.peer.respond(
        b"1\r\n{\r\n1\r\n}\r\n0\r\nX-Synthetic: yes\r\n\r\n",
        headers=[("Transfer-Encoding", "chunked")],
    )
    result = await case.m._capture_https_read(case.catalog, 0)
    assert result.body == b"{}"


async def test_chunked_trailer_total_is_bounded(case):
    trailers = b"".join(b"X-Synthetic: " + b"a" * 8000 + b"\r\n" for _ in range(9))
    case.peer.respond(
        b"2\r\n{}\r\n0\r\n" + trailers + b"\r\n", headers=[("Transfer-Encoding", "chunked")]
    )
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await case.m._capture_https_read(case.catalog, 0)


class PeerFile(io.RawIOBase):
    def __init__(self, peer):
        self.peer = peer
        super().__init__()

    def readable(self):
        return True

    def readinto(self, buffer):
        self.peer.event("read")
        self.peer.reading.set()
        assert self.peer.allow_read.wait(2)
        self.peer.tick += self.peer.read_step
        amount = min(len(buffer), len(self.peer.wire), self.peer.fragment)
        buffer[:amount] = self.peer.wire[:amount]
        del self.peer.wire[:amount]
        return amount

    def close(self):
        self.peer.event("file_close")
        super().close()


class Peer:
    def __init__(self):
        self.events = []
        self.sent = bytearray()
        self.wire = bytearray()
        self.timeouts = []
        self.threads = set()
        self.leaf = LEAF
        self.protocol = "TLSv1.3"
        self.tick = 100.0
        self.read_step = 0.0
        self.connect_step = 0.0
        self.handshake_step = 0.0
        self.fragment = 16384
        self.fail = None
        self.reading, self.closing = threading.Event(), threading.Event()
        self.allow_read, self.allow_close = threading.Event(), threading.Event()
        self.allow_read.set()
        self.allow_close.set()
        self.respond()

    def event(self, name):
        self.events.append(name)
        self.threads.add(threading.get_ident())
        if self.fail == name:
            raise OSError("synthetic private failure")

    def respond(self, body=b'{"synthetic_private":"response"}', status=200, headers=None):
        if headers is None:
            headers = [("Content-Length", str(len(body))), ("Content-Type", "application/json")]
        wire = f"HTTP/1.1 {status} Synthetic\r\n".encode()
        wire += b"".join(f"{key}: {value}\r\n".encode() for key, value in headers)
        self.wire = bytearray(wire + b"\r\n" + body)

    def settimeout(self, value):
        self.timeouts.append(value)

    def connect(self, address):
        assert address == ("127.0.0.1", 9200)
        self.event("connect")
        self.tick += self.connect_step

    def do_handshake(self):
        self.event("handshake")
        self.tick += self.handshake_step

    def getpeercert(self, binary_form):
        assert binary_form is True
        self.event("peer_leaf")
        return self.leaf

    def version(self):
        self.event("protocol")
        return self.protocol

    def sendall(self, data):
        self.event("send")
        self.sent.extend(data)

    def makefile(self, mode, buffering=0):
        assert mode == "rb" and buffering == 0
        return PeerFile(self)

    def close(self):
        self.event("close")
        self.closing.set()
        assert self.allow_close.wait(2)


@pytest.fixture
def case(monkeypatch):
    m = module()
    peers, contexts = [], []
    current = Peer()

    def socket_factory(family, kind):
        assert family == m.AF_INET and kind == m.SOCK_STREAM
        peers.append(current)
        current.event("socket")
        return current

    class Context:
        def __init__(self, protocol):
            assert protocol == ssl.PROTOCOL_TLS_CLIENT
            self.check_hostname = True
            self.verify_mode = ssl.CERT_REQUIRED
            self.minimum_version = ssl.TLSVersion.TLSv1_2
            self.loaded = []
            self.alpn = None
            contexts.append(self)

        def load_verify_locations(self, *, cadata):
            assert cadata == CA.decode("ascii")
            self.loaded.append(cadata)

        def set_alpn_protocols(self, value):
            self.alpn = value

        def wrap_socket(self, raw, *, server_hostname, do_handshake_on_connect):
            assert raw is current
            assert server_hostname == "127.0.0.1" and do_handshake_on_connect is False
            current.event("wrap")
            return current

    monkeypatch.setattr(m, "socket", socket_factory)
    monkeypatch.setattr(m, "SSLContext", Context)
    monkeypatch.setattr(m, "monotonic", lambda: current.tick)
    keys = tuple(
        m.SecuredHttpsKey(
            role,
            "synthetic-" + role,
            "synthetic-key-" + role,
            SecretStr(base64.b64encode(f"synthetic-{role}:private-{role}".encode()).decode()),
        )
        for role in ROLES
    )
    catalog = m.SecuredHttpsReadCatalog(
        UUID(int=1),
        AccessEpochPermissions("rag", ((UUID(int=2), None),)),
        CA,
        sha256(LEAF).hexdigest(),
        keys,
    )
    return SimpleNamespace(m=m, peer=current, peers=peers, contexts=contexts, catalog=catalog)


@pytest.mark.parametrize("slot", range(9))
async def test_fixed_nine_slot_catalog_validates_tls_before_sending(case, slot):
    c = case
    result = await c.m._capture_https_read(c.catalog, slot)
    assert result.body == b'{"synthetic_private":"response"}'
    assert result.protocol == "TLSv1.3" and result.leaf_der_sha256 == sha256(LEAF).hexdigest()
    assert "response" not in repr(result)
    assert (
        c.peer.events.index("handshake")
        < c.peer.events.index("peer_leaf")
        < c.peer.events.index("send")
    )
    assert c.peer.events[-1] == "close"
    assert len(c.peer.threads) == 1 and threading.get_ident() not in c.peer.threads
    method = "POST" if slot in {4, 6, 8} else "GET"
    routes = [
        "/",
        "/_cluster/state/master_node,nodes",
        "/_nodes/settings,http,transport,remote_cluster_server,jvm?flat_settings=true",
    ]
    route = (
        routes[slot]
        if slot < 3
        else "/_security/user/_has_privileges"
        if method == "POST"
        else "/_security/_authenticate"
    )
    wire = bytes(c.peer.sent)
    assert wire.startswith(f"{method} {route} HTTP/1.1\r\n".encode())
    role = "collector" if slot < 3 else ROLES[(slot - 3) // 2]
    secret = next(key.encoded.get_secret_value() for key in c.catalog.keys if key.role == role)
    assert b"Authorization: ApiKey " + secret.encode() + b"\r\n" in wire
    assert b"Accept-Encoding: identity\r\n" in wire and b"Connection: close\r\n" in wire
    assert secret not in repr(c.catalog)
    if method == "POST":
        body = json.loads(wire.split(b"\r\n\r\n", 1)[1])
        assert set(body) == {"cluster", "index", "application"}
        assert body["index"][1]["names"][:2] == ["*", ".security"]
        assert all(row["allow_restricted_indices"] is False for row in body["index"])
    else:
        assert wire.endswith(b"\r\n\r\n")
    ctx = c.contexts[0]
    assert ctx.check_hostname is True and ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.loaded == [CA.decode()] and ctx.alpn == ["http/1.1"]


@pytest.mark.parametrize(
    "change", ["wrong_leaf", "old_tls", "no_tls", "handshake", "wrap", "connect"]
)
async def test_tls_failure_sends_no_credentials_and_closes(case, change):
    c = case
    if change == "wrong_leaf":
        c.peer.leaf = b"other"
    elif change == "old_tls":
        c.peer.protocol = "TLSv1.1"
    elif change == "no_tls":
        c.peer.protocol = None
    else:
        c.peer.fail = change
    with pytest.raises(ValueError) as exc:
        await c.m._capture_https_read(c.catalog, 3)
    assert str(exc.value) == "secured_https_read_denied"
    assert c.peer.sent == b"" and "close" in c.peer.events
    assert "private" not in str(exc.value)


@pytest.mark.parametrize("status", [201, 301, 302, 401, 403, 500])
async def test_http_status_does_not_redirect_retry_or_return_body(case, status):
    c = case
    c.peer.respond(
        status=status,
        headers=[("Location", "https://example.invalid/private"), ("Content-Length", "0")],
    )
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await c.m._capture_https_read(c.catalog, 0)
    assert len(c.peers) == 1 and c.peer.sent.count(b"GET ") == 1
    assert "close" in c.peer.events


@pytest.mark.parametrize(
    "headers",
    [
        [("Content-Encoding", "gzip")],
        [("Content-Encoding", "identity"), ("Content-Encoding", "identity")],
        [("Content-Length", "2"), ("Content-Length", "2")],
        [("Content-Length", "-1")],
        [("Content-Length", "2.0")],
        [("Content-Length", "2097153")],
        [("Transfer-Encoding", "gzip")],
        [("Transfer-Encoding", "chunked"), ("Content-Length", "2")],
    ],
    ids=[
        "compressed",
        "duplicate_encoding",
        "duplicate_length",
        "negative",
        "float",
        "oversize",
        "transfer",
        "ambiguous",
    ],
)
async def test_ambiguous_or_unbounded_framing_is_rejected(case, headers):
    c = case
    c.peer.respond(body=b"{}", headers=headers)
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await c.m._capture_https_read(c.catalog, 0)


@pytest.mark.parametrize("slot,limit", [(0, 2097152), (3, 262144)])
async def test_actual_body_bound_is_enforced_without_content_length(case, slot, limit):
    c = case
    c.peer.respond(body=b"x" * (limit + 1), headers=[("Connection", "close")])
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await c.m._capture_https_read(c.catalog, slot)


async def test_incomplete_length_is_rejected(case):
    c = case
    c.peer.respond(body=b"{}", headers=[("Content-Length", "5")])
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await c.m._capture_https_read(c.catalog, 0)


@pytest.mark.parametrize("stage", ["connect", "handshake", "headers", "body"])
async def test_one_five_second_budget_covers_all_io_not_each_read(case, stage):
    c = case
    if stage == "connect":
        c.peer.connect_step = 5.1
    elif stage == "handshake":
        c.peer.connect_step, c.peer.handshake_step = 2.0, 3.1
    elif stage == "headers":
        c.peer.fragment, c.peer.read_step = 1, 0.2
    else:
        c.peer.fragment, c.peer.read_step = 50, 0.5
        c.peer.respond(body=b"x" * 4096)
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await c.m._capture_https_read(c.catalog, 0)
    assert all(0 < timeout <= 5.0 for timeout in c.peer.timeouts)
    if stage in {"connect", "handshake"}:
        assert c.peer.sent == b""
    assert "close" in c.peer.events


@pytest.mark.parametrize("stage", ["read", "close"])
async def test_repeated_cancellation_waits_for_owned_cleanup_and_preserves_first(case, stage):
    c = case
    reached = c.peer.reading if stage == "read" else c.peer.closing
    release = c.peer.allow_read if stage == "read" else c.peer.allow_close
    release.clear()
    task = asyncio.create_task(c.m._capture_https_read(c.catalog, 3))
    assert await asyncio.wait_for(asyncio.to_thread(reached.wait, 2), 3)
    task.cancel("first")
    await asyncio.sleep(0)
    task.cancel("second")
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError) as exc:
        await asyncio.wait_for(task, 3)
    assert exc.value.args == ("first",)
    assert c.peer.events[-1] == "close"
    assert len(c.peer.threads) == 1 and threading.get_ident() not in c.peer.threads


async def test_failed_close_never_publishes_a_response(case):
    c = case
    c.peer.fail = "close"
    with pytest.raises(ValueError) as exc:
        await c.m._capture_https_read(c.catalog, 3)
    assert str(exc.value) == "secured_https_read_denied"
    assert exc.value.__notes__ == ["secured_https_cleanup_unverified"]


async def test_cancelled_failed_close_keeps_primary_cancel_and_cleanup_note(case):
    c = case
    c.peer.allow_read.clear()
    c.peer.fail = "close"
    task = asyncio.create_task(c.m._capture_https_read(c.catalog, 3))
    assert await asyncio.wait_for(asyncio.to_thread(c.peer.reading.wait, 2), 3)
    task.cancel("first")
    await asyncio.sleep(0)
    c.peer.allow_read.set()
    with pytest.raises(asyncio.CancelledError) as exc:
        await task
    assert exc.value.args == ("first",)
    assert exc.value.__notes__ == ["secured_https_cleanup_unverified"]


@pytest.mark.parametrize("slot", [True, -1, 9, 1.0, "1"])
async def test_invalid_slot_never_constructs_transport(case, slot):
    c = case
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await c.m._capture_https_read(c.catalog, slot)
    assert c.peers == []


@pytest.mark.parametrize(
    "change",
    ["ca_type", "ca_oversize", "leaf", "roles", "secret", "encoded_id", "epoch", "permissions"],
)
async def test_invalid_catalog_cannot_select_another_route_or_secret(case, change):
    c = case
    catalog = c.catalog
    if change == "ca_type":
        catalog = replace(catalog, http_ca_pem="text")
    elif change == "ca_oversize":
        catalog = replace(catalog, http_ca_pem=b"a" * 16385)
    elif change == "leaf":
        catalog = replace(catalog, http_leaf_sha256="other")
    elif change == "roles":
        catalog = replace(catalog, keys=(catalog.keys[0],) * 3)
    elif change == "secret":
        catalog = replace(
            catalog, keys=(replace(catalog.keys[0], encoded="private"), *catalog.keys[1:])
        )
    elif change == "encoded_id":
        catalog = replace(
            catalog, keys=(replace(catalog.keys[0], key_id="other"), *catalog.keys[1:])
        )
    elif change == "epoch":
        catalog = replace(catalog, epoch_id=UUID(int=0))
    else:
        catalog = replace(catalog, permissions={"privileges": "all"})
    with pytest.raises(ValueError, match="^secured_https_read_denied$"):
        await c.m._capture_https_read(catalog, 0)
    assert c.peers == []
