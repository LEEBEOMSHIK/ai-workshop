"""Fixed route inputs and private wire decoding; no operator attestations."""

import asyncio
import base64
import hashlib
import json
import math
import os
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext, _freeze
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    RawDeploymentReadback,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth import FinalAuthBinding
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import FinalAuthBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_process import (
    RecordedFinalAuthentication,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_collection import (
    RecordedInventoryCollector,
)
from ai_workshop.labs.rag.indexing.access_epoch_observations import (
    RouteObservation,
    validate_routes,
)
from ai_workshop.labs.rag.indexing.access_epoch_process import _binary_sha
from ai_workshop.labs.rag.indexing.access_epoch_types import ReservedCutoverAction, canonical_json
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CONTAINER,
    DOCKER_EXE,
    NETWORK,
    ORIGINAL_IMAGE_ID,
)

_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
_JAVA = "/usr/share/elasticsearch/jdk/bin/java"
_JAVA_FLAGS = ("-Xms16m", "-Xmx128m", "-XX:ActiveProcessorCount=1", "-XX:-UsePerfData")
_JAVA_PREFIX = (
    "/usr/bin/env",
    "-u",
    "JAVA_TOOL_OPTIONS",
    "-u",
    "JDK_JAVA_OPTIONS",
    "-u",
    "_JAVA_OPTIONS",
    _JAVA,
)
_SUPPORT_SOURCE = b"""class RouteRuntimeProbe {
public static void main(String[] args) {
System.out.print("{\\\"schema_version\\\":1,\\\"java_feature\\\":"
+ Runtime.version().feature() + ",\\\"source_level\\\":21,\\\"compiler_present\\\":"
+ ModuleLayer.boot().findModule("jdk.compiler").isPresent() + "}");
}
}
"""
_SUPPORT_TEMPLATE = hashlib.sha256(_SUPPORT_SOURCE).hexdigest()

_HOST_SOURCE = r"""import base64,hashlib,http.client,json,ssl,sys
p=json.loads(sys.stdin.buffer.read(65537))
assert set(p)=={'purpose','ca','leaf','authorization','wrong_ca'}
c=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
c.load_verify_locations(cadata=base64.b64decode(p['ca'],validate=True).decode('ascii'))
h=http.client.HTTPSConnection('127.0.0.1',9200,context=c,timeout=5)
try:
 h.connect()
except ssl.SSLCertVerificationError:
 if not p['wrong_ca']: raise
 print(json.dumps({'schema_version':1,'purpose':p['purpose'],'code':'ca_rejected'},sort_keys=True,separators=(',',':')))
 sys.exit(0)
if p['wrong_ca']: raise ValueError('unexpected_tls')
assert hashlib.sha256(h.sock.getpeercert(binary_form=True)).hexdigest()==p['leaf']
protocol=h.sock.version()
headers={'Accept-Encoding':'identity','Connection':'close'}
if p['authorization']: headers['Authorization']='ApiKey '+p['authorization']
h.request('GET','/_security/_authenticate',headers=headers)
r=h.getresponse()
assert r.getheader('Content-Encoding') in (None,'identity')
body=r.read(262145)
assert len(body)<=262144
print(json.dumps({'schema_version':1,'purpose':p['purpose'],'code':'https','protocol':protocol,'chain_verified':True,'leaf_der_sha256':p['leaf'],'status':r.status,'body_b64':base64.b64encode(body).decode('ascii')},sort_keys=True,separators=(',',':')))
h.close()
"""

_JAVA_TEMPLATE = r"""import javax.net.ssl.*;
import java.net.*; import java.io.*; import java.security.*;
import java.security.cert.*; import java.security.spec.*; import java.util.*;
class NativeRouteProbe {
static boolean verified=false;
static byte[] b(String x){return Base64.getDecoder().decode(x);}
static X509Certificate cert(String x)throws Exception{return (X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(new ByteArrayInputStream(b(x)));}
static String fp(X509Certificate x)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(x.getEncoded()));}
static void check(X509Certificate[] chain)throws CertificateException{
try{if(!fp(chain[0]).equals("<LEAF>"))throw new CertificateException();verified=true;}
catch(Exception e){throw new CertificateException();}}
static void emit(String code,String extra){System.out.print("{\"schema_version\":1,\"purpose\":\"<PURPOSE>\",\"code\":\""+code+"\""+extra+"}");}
public static void main(String[] args)throws Exception{
KeyStore trust=KeyStore.getInstance(KeyStore.getDefaultType());trust.load(null,null);trust.setCertificateEntry("project",cert("<CA>"));
TrustManagerFactory tf=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());tf.init(trust);
X509ExtendedTrustManager d=(X509ExtendedTrustManager)tf.getTrustManagers()[0];
X509ExtendedTrustManager t=new X509ExtendedTrustManager(){
public X509Certificate[] getAcceptedIssuers(){return d.getAcceptedIssuers();}
public void checkClientTrusted(X509Certificate[] x,String a)throws CertificateException{d.checkClientTrusted(x,a);}
public void checkClientTrusted(X509Certificate[] x,String a,Socket s)throws CertificateException{d.checkClientTrusted(x,a,s);}
public void checkClientTrusted(X509Certificate[] x,String a,SSLEngine e)throws CertificateException{d.checkClientTrusted(x,a,e);}
public void checkServerTrusted(X509Certificate[] x,String a)throws CertificateException{d.checkServerTrusted(x,a);check(x);}
public void checkServerTrusted(X509Certificate[] x,String a,Socket s)throws CertificateException{d.checkServerTrusted(x,a,s);check(x);}
public void checkServerTrusted(X509Certificate[] x,String a,SSLEngine e)throws CertificateException{d.checkServerTrusted(x,a,e);check(x);}
};
KeyManager[] managers=new KeyManager[0];
if(<CLIENT>){KeyStore own=KeyStore.getInstance(KeyStore.getDefaultType());own.load(null,null);
String pem=new String(b("<KEY>"),java.nio.charset.StandardCharsets.US_ASCII);
byte[] der=b(pem.replace("-----BEGIN PRIVATE KEY-----","").replace("-----END PRIVATE KEY-----","").replaceAll("\\s",""));
PrivateKey key=KeyFactory.getInstance("EC").generatePrivate(new PKCS8EncodedKeySpec(der));
own.setKeyEntry("node",key,new char[0],new java.security.cert.Certificate[]{cert("<CERT>"),cert("<CA>")});
KeyManagerFactory kf=KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());kf.init(own,new char[0]);managers=kf.getKeyManagers();Arrays.fill(der,(byte)0);}
SSLContext context=SSLContext.getInstance("TLS");context.init(managers,new TrustManager[]{t},null);
if(<TRANSPORT>){try(SSLSocket socket=(SSLSocket)context.getSocketFactory().createSocket()){
socket.connect(new InetSocketAddress("<HOST>",9300),5000);socket.setSoTimeout(5000);socket.setEnabledProtocols(new String[]{"TLSv1.2"});
SSLParameters parameters=socket.getSSLParameters();parameters.setEndpointIdentificationAlgorithm("HTTPS");socket.setSSLParameters(parameters);
try{socket.startHandshake();if(!<CLIENT>)socket.getInputStream().read();
if(!<CLIENT>||!verified||!socket.getSession().getProtocol().equals("TLSv1.2"))throw new Exception();
emit("mutual_tls",",\"protocol\":\"TLSv1.2\",\"chain_verified\":true,\"leaf_der_sha256\":\"<LEAF>\"");
}catch(SSLException failure){String message=failure.getMessage();
if(<CLIENT>||!verified)throw new Exception();
String alert=message.equals("Received fatal alert: bad_certificate")?"bad_certificate":message.equals("Received fatal alert: certificate_required")?"certificate_required":"";
if(alert.isEmpty())throw new Exception();
emit("client_certificate_rejected",",\"protocol\":\"TLSv1.2\",\"chain_verified\":true,\"leaf_der_sha256\":\"<LEAF>\",\"fatal_alert\":\""+alert+"\"");}
}return;}
URL url=new URI("https://<HOST>:9200<ROUTE>").toURL();
HttpsURLConnection connection=(HttpsURLConnection)url.openConnection(Proxy.NO_PROXY);connection.setSSLSocketFactory(context.getSocketFactory());
connection.setConnectTimeout(5000);connection.setReadTimeout(5000);connection.setInstanceFollowRedirects(false);
connection.setRequestProperty("Accept-Encoding","identity");connection.setRequestProperty("Connection","close");
if(!"<AUTH>".isEmpty())connection.setRequestProperty("Authorization","ApiKey <AUTH>");
connection.connect();if(!verified)throw new Exception();
String protocol=connection.getSSLSession().orElseThrow().getProtocol();int status=connection.getResponseCode();
String encoding=connection.getHeaderField("Content-Encoding");if(encoding!=null&&!encoding.equals("identity"))throw new Exception();
InputStream stream=status>=400?connection.getErrorStream():connection.getInputStream();if(stream==null)throw new Exception();
byte[] body=stream.readNBytes(524289);if(body.length>524288)throw new Exception();
emit("https",",\"protocol\":\""+protocol+"\",\"chain_verified\":true,\"leaf_der_sha256\":\"<LEAF>\",\"status\":"+status+",\"body_b64\":\""+Base64.getEncoder().encodeToString(body)+"\"");
stream.close();connection.disconnect();Arrays.fill(body,(byte)0);
}
}
"""  # noqa: E501 -- fixed Java source is versioned separately from private RAM payload
_ROUTE_TEMPLATE_DIGEST = hashlib.sha256((_JAVA_TEMPLATE + _HOST_SOURCE).encode()).hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise _denied()
        value[key] = item
    return value


def _load(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes or not 0 < len(raw) <= 4_194_304:
        raise _denied()

    def finite(token: str) -> float:
        number = float(token)
        if not math.isfinite(number):
            raise _denied()
        return number

    value = json.loads(
        raw.decode("utf-8", errors="strict"),
        object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(_denied()),
        parse_float=finite,
    )
    if type(value) is not dict:
        raise _denied()
    return value


def _python_sha() -> str:
    path = PROJECT_ROOT / "backend/.venv/Scripts/python.exe"
    if path.is_symlink() or not path.is_file():
        raise _unsupported()
    data = path.read_bytes()
    if not 0 < len(data) <= 32 * 1024 * 1024:
        raise _unsupported()
    return hashlib.sha256(data).hexdigest()


class RouteProbeKind(StrEnum):
    DAEMON_ID_BEFORE = "daemon_id_before"
    CONTAINER_BEFORE = "container_before"
    IMAGE_BEFORE = "image_before"
    VOLUME_BEFORE = "volume_before"
    NETWORK_BEFORE = "network_before"
    ALL_IDS_BEFORE = "all_ids_before"
    SECURITY_CONFIG_BEFORE = "security_config_before"
    NODES_INFO_BEFORE = "nodes_info_before"
    IDENTITY_STATE_BEFORE = "identity_state_before"
    HOST_AUTH = "host_auth"
    HOST_ANONYMOUS = "host_anonymous"
    HOST_WRONG_CA = "host_wrong_ca"
    GUEST_DNS_AUTH = "guest_dns_auth"
    GUEST_IP_AUTH = "guest_ip_auth"
    GUEST_DNS_ANONYMOUS = "guest_dns_anonymous"
    GUEST_IP_ANONYMOUS = "guest_ip_anonymous"
    TRANSPORT_CERTIFICATE = "transport_certificate"
    TRANSPORT_NO_CERTIFICATE = "transport_no_certificate"
    NODES_INFO_AFTER = "nodes_info_after"
    IDENTITY_STATE_AFTER = "identity_state_after"
    DAEMON_ID_AFTER = "daemon_id_after"
    CONTAINER_AFTER = "container_after"
    IMAGE_AFTER = "image_after"
    VOLUME_AFTER = "volume_after"
    NETWORK_AFTER = "network_after"
    ALL_IDS_AFTER = "all_ids_after"
    SECURITY_CONFIG_AFTER = "security_config_after"


def _denied() -> ValueError:
    return ValueError("native_route_unverified")


def _unsupported() -> ValueError:
    return ValueError("native_route_unsupported")


@dataclass(frozen=True, slots=True, eq=False)
class RouteCommand:
    purpose: RouteProbeKind
    argv: tuple[str, ...]
    private_stdin: bytes | None = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class PinnedRouteRuntime:
    nonce: UUID
    java_feature: int
    source_level: int
    compiler_present: bool
    template_sha256: str
    deployment_sha256: str
    docker_binary_sha256: str
    python_binary_sha256: str


@dataclass(frozen=True, slots=True)
class PrivateRouteResponse:
    exit_code: int
    stdout: bytes = field(repr=False)
    stderr: bytes = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class DecodedRouteProbe:
    purpose: RouteProbeKind
    body: bytes = field(repr=False)
    public_json: str


def _decode_wire(
    purpose: RouteProbeKind, raw: bytes, leaf_sha: str, collector_id: str, collector_name: str
) -> tuple[bytes, dict[str, Any]]:
    """Pure structural parser. Its return value is never an issued capability."""
    try:
        if type(purpose) is not RouteProbeKind:
            raise _denied()
        verb = purpose.value.removesuffix("_before").removesuffix("_after")
        value = _load(raw)
        if (
            type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
            or value.get("purpose") != purpose.value
        ):
            raise _denied()
        if verb == "host_wrong_ca":
            if value != {"schema_version": 1, "purpose": purpose.value, "code": "ca_rejected"}:
                raise _denied()
            return b"", value
        if (
            value.get("chain_verified") is not True
            or value.get("leaf_der_sha256") != leaf_sha
            or value.get("protocol") not in {"TLSv1.2", "TLSv1.3"}
        ):
            raise _denied()
        base = {
            "schema_version",
            "purpose",
            "code",
            "protocol",
            "chain_verified",
            "leaf_der_sha256",
        }
        if verb.startswith("transport_"):
            client = verb == "transport_certificate"
            if (
                value.get("code") != ("mutual_tls" if client else "client_certificate_rejected")
                or value["protocol"] != "TLSv1.2"
                or set(value) != base | (set() if client else {"fatal_alert"})
                or not client
                and value.get("fatal_alert") not in {"bad_certificate", "certificate_required"}
            ):
                raise _denied()
            return b"", value
        if (
            set(value) != base | {"status", "body_b64"}
            or value.get("code") != "https"
            or type(value["status"]) is not int
            or type(value["body_b64"]) is not str
        ):
            raise _denied()
        body = base64.b64decode(value["body_b64"], validate=True)
        if not 0 < len(body) <= 524288 or base64.b64encode(body).decode() != value["body_b64"]:
            raise _denied()
        wire = _load(body)
        if "anonymous" in verb:
            if (
                value["status"] != 401
                or type(wire.get("status")) is not int
                or wire["status"] != 401
                or type(wire.get("error")) is not dict
                or wire["error"].get("type") != "security_exception"
            ):
                raise _denied()
        elif (
            value["status"] != 200
            or verb not in {"nodes_info", "identity_state"}
            and (
                wire.get("authentication_type") != "api_key"
                or wire.get("enabled") is not True
                or wire.get("username") != "elastic"
                or wire.get("api_key")
                != {"id": collector_id, "name": collector_name, "managed_by": "elasticsearch"}
            )
        ):
            raise _denied()
        return body, {key: item for key, item in value.items() if key != "body_b64"}
    except Exception:
        raise _denied() from None


def _route_observations(evidence: dict[str, object]) -> tuple[RouteObservation, ...]:
    """Closed public projection only; this does not issue route authority."""
    rows = tuple(
        RouteObservation(
            name,
            "admitted" if name in {"host_http", "guest_http", "transport"} else "excluded",
            name in {"host_http", "guest_http", "transport"},
            name in {"host_http", "guest_http", "transport"},
            name == "transport",
            hashlib.sha256(canonical_json({"evidence": value}).encode()).hexdigest(),
        )
        for name, value in evidence.items()
    )
    validate_routes(rows)
    return rows


class NativeRouteCommands:
    def __init__(self, context: NativeControlContext) -> None:
        if type(context) is not NativeControlContext:
            raise _denied()
        context.assert_sources()
        self._context = context
        self._context_pin = context
        self._template_signature = self._templates()
        self._support_started = False
        self._support_failed = False
        self._support: PinnedRouteRuntime | None = None
        self._support_signature: object = None
        self._support_issued: dict[PinnedRouteRuntime, object] = {}
        self._commands: dict[RouteCommand, object] = {}
        self._purposes: set[RouteProbeKind] = set()
        self._decoded: dict[RouteCommand, tuple[object, object, DecodedRouteProbe]] = {}

    @property
    def context(self) -> NativeControlContext:
        if self._context is not self._context_pin:
            raise _denied()
        return self._context

    @staticmethod
    def _templates() -> object:
        return _freeze(
            (
                DOCKER_EXE,
                _PIPE,
                _JAVA_PREFIX,
                _JAVA_FLAGS,
                _SUPPORT_SOURCE,
                _JAVA_TEMPLATE,
                _HOST_SOURCE,
                _SUPPORT_TEMPLATE,
                _ROUTE_TEMPLATE_DIGEST,
            )
        )

    def assert_supported(self) -> None:
        try:
            if self._context is not self._context_pin:
                raise _unsupported()
            self._context.assert_sources()
            if self._template_signature != self._templates():
                raise _unsupported()
            cap = self._support
            if (
                self._support_started is not True
                or self._support_failed is not False
                or type(cap) is not PinnedRouteRuntime
                or self._support_signature != _freeze(cap)
                or self._support_issued.get(cap) != _freeze(cap)
                or cap.deployment_sha256 != self._context.observation.identity.deployment_sha256
                or cap.template_sha256 != _SUPPORT_TEMPLATE
                or _binary_sha() != cap.docker_binary_sha256
                or _python_sha() != cap.python_binary_sha256
            ):
                raise _unsupported()
        except Exception:
            raise _unsupported() from None

    def _probe_support(self) -> bytes:
        """One fixed public source-launch query; no arbitrary command input."""
        env = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
        }
        result = subprocess.run(
            (
                DOCKER_EXE,
                "--host",
                _PIPE,
                "exec",
                "--interactive",
                CONTAINER,
                *_JAVA_PREFIX,
                *_JAVA_FLAGS,
                "--source",
                "21",
                "/dev/stdin",
            ),
            input=_SUPPORT_SOURCE,
            shell=False,
            capture_output=True,
            timeout=30,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if (
            type(result.returncode) is not int
            or result.returncode != 0
            or type(result.stdout) is not bytes
            or type(result.stderr) is not bytes
            or result.stderr != b""
            or not 0 < len(result.stdout) <= 8192
        ):
            raise _unsupported()
        return result.stdout

    async def observe_support(self) -> None:
        """Preepoch readonly support receipt; never an epoch/control capability."""
        try:
            if self._context is not self._context_pin:
                raise _unsupported()
            self._context.assert_sources()
            if (
                self._support_started is not False
                or self._support_failed is not False
                or self._context.epoch is not None
                or self._template_signature != self._templates()
            ):
                raise _unsupported()
            self._support_started = True
            before = await self._context.original.observe_original(self._context.claim.snapshot)
            self._context.assert_sources()
            if before != self._context.observation.identity:
                raise _unsupported()
            docker_sha, python_sha = _binary_sha(), _python_sha()
            value = _load(await asyncio.to_thread(self._probe_support))
            self._context.assert_sources()
            if (
                set(value) != {"schema_version", "java_feature", "source_level", "compiler_present"}
                or type(value["schema_version"]) is not int
                or value["schema_version"] != 1
                or type(value["java_feature"]) is not int
                or not 21 <= value["java_feature"] <= 99
                or type(value["source_level"]) is not int
                or value["source_level"] != 21
                or value["compiler_present"] is not True
                or docker_sha != _binary_sha()
                or python_sha != _python_sha()
            ):
                raise _unsupported()
            after = await self._context.original.observe_original(self._context.claim.snapshot)
            self._context.assert_sources()
            if before != after:
                raise _unsupported()
            cap = PinnedRouteRuntime(
                uuid4(),
                value["java_feature"],
                21,
                True,
                _SUPPORT_TEMPLATE,
                before.deployment_sha256,
                docker_sha,
                python_sha,
            )
            self._support, self._support_signature = cap, _freeze(cap)
            self._support_issued[cap] = self._support_signature
            self.assert_supported()
        except BaseException as exc:
            self._support_failed = True
            self._support = None
            self._support_signature = None
            self._support_issued.clear()
            if isinstance(exc, Exception):
                raise _unsupported() from None
            raise

    def _runtime(self) -> FinalAuthBinding:
        self.assert_supported()
        c = self._context
        c.assert_owned()
        factory, auth, deployment = c.final_auth_factory, c.final_authentication, c.deployment
        repository, journal, native, store = c.repository, c.journal, c.native, c.store
        keys, bootstrap_factory, bootstrap = c.keys, c.bootstrap_factory, c.bootstrap_commands
        final, observation, tls, assets = c.final, c.final_auth, c.tls, c.tls_assets
        apps, inventory = c.app_retirement, c.final_inventory
        collector, preservation = c.final_inventory_issuer, c.final_preservation
        if (
            type(factory) is not FinalAuthBindingFactory
            or type(auth) is not RecordedFinalAuthentication
            or type(deployment) is not DeploymentCommands
            or auth.factory is not factory
            or factory.repository is not repository
            or factory.journal is not journal
            or factory.deployment is not deployment
            or keys is None
            or bootstrap_factory is None
            or bootstrap is None
            or cast(object, factory.keys) is not keys
            or factory.bootstrap_factory is not bootstrap_factory
            or factory.bootstrap is not bootstrap
            or final is None
            or observation is None
            or tls is None
            or assets is None
            or apps is None
            or inventory is None
            or type(collector) is not RecordedInventoryCollector
            or preservation is None
        ):
            raise _denied()
        binding = auth.binding
        factory.assert_issued(binding)
        auth.assert_issued(observation)
        deployment.assert_observed(final)
        tls.assert_issued(assets)
        collector.assert_issued(inventory)
        if (
            auth.final is not final
            or binding.container_id != final.container_id
            or auth.repository is not repository
            or auth.journal is not journal
            or auth.native is not native
            or factory.tls is not tls
            or cast(object, factory.store) is not store
        ):
            raise _denied()
        c.assert_owned()
        # Issuer callbacks cannot replace the just-validated synchronous graph.
        if (
            c._final_auth_factory is not factory
            or c._final_authentication is not auth
            or auth.binding is not binding
            or c._deployment is not deployment
            or c._repository is not repository
            or c._journal is not journal
            or c._native is not native
            or c._store is not store
            or c._tls is not tls
            or c._keys is not keys
            or c._bootstrap_factory is not bootstrap_factory
            or c._bootstrap_commands is not bootstrap
            or auth.factory is not factory
            or auth.final is not final
            or auth.repository is not repository
            or auth.journal is not journal
            or auth.native is not native
            or factory.repository is not repository
            or factory.journal is not journal
            or factory.deployment is not deployment
            or factory.tls is not tls
            or cast(object, factory.store) is not store
            or cast(object, factory.keys) is not keys
            or factory.bootstrap_factory is not bootstrap_factory
            or factory.bootstrap is not bootstrap
            or keys.parent is not repository
            or bootstrap_factory.repository is not repository
            or bootstrap_factory.journal is not journal
            or bootstrap_factory.deployment is not deployment
            or c._collectors.get("final") is not collector
            or any(
                c._caps.get(name) is not cap
                for name, cap in (
                    ("final", final),
                    ("final_auth", observation),
                    ("tls_assets", assets),
                    ("app_retirement", apps),
                    ("final_inventory", inventory),
                    ("final_preservation", preservation),
                )
            )
        ):
            raise _denied()
        return binding

    def _material(self) -> tuple[bytes, ...]:
        c = self._context
        self._runtime()
        tls, assets = c.tls, c.tls_assets
        assert tls is not None and assets is not None
        material = tuple(tls._read(Path(path)) for path in assets.leaf_locations)
        c.assert_owned()
        if len(material) != 6 or any(
            type(x) is not bytes or not 0 < len(x) <= 16384 for x in material
        ):
            raise _denied()
        return cast(tuple[bytes, ...], material)

    def command(self, purpose: RouteProbeKind) -> RouteCommand:
        try:
            if type(purpose) is not RouteProbeKind or purpose in self._purposes:
                raise _denied()
            binding = self._runtime()
            c = self._context
            assert c.final is not None
            original = (DOCKER_EXE, "--host", _PIPE)
            verb = purpose.value.removesuffix("_before").removesuffix("_after")
            commands: dict[str, tuple[str, ...]] = {
                "daemon_id": ("info", "--format", '{"ID":{{json .ID}},"OSType":{{json .OSType}}}'),
                "container": ("container", "inspect", c.final.container_id),
                "image": ("image", "inspect", ORIGINAL_IMAGE_ID),
                "volume": ("volume", "inspect", "ai-workshop_elasticsearch-data"),
                "network": ("network", "inspect", NETWORK),
                "all_ids": ("ps", "--all", "--no-trunc", "--format", "{{.ID}}"),
                "security_config": (
                    "exec",
                    c.final.container_id,
                    "/usr/bin/cat",
                    "/usr/share/elasticsearch/config/elasticsearch.yml",
                ),
            }
            if verb in commands:
                argv, private = (*original, *commands[verb]), None
            else:
                material = self._material()
                manifest = _load(cast(Any, c.tls_assets).manifest_json.encode())
                collector = next(key for key in binding.keys if key.role == "collector")
                authorization = (
                    ""
                    if "anonymous" in verb
                    or verb == "host_wrong_ca"
                    or verb.startswith("transport_")
                    else collector.encoded.get_secret_value()
                )
                if verb.startswith("host_"):
                    packet = {
                        "purpose": purpose.value,
                        "ca": base64.b64encode(
                            material[5] if verb == "host_wrong_ca" else material[2]
                        ).decode(),
                        "leaf": manifest["http_leaf_der_sha256"],
                        "authorization": authorization,
                        "wrong_ca": verb == "host_wrong_ca",
                    }
                    argv = (
                        str(PROJECT_ROOT / "backend/.venv/Scripts/python.exe"),
                        "-I",
                        "-c",
                        _HOST_SOURCE,
                    )
                    private = canonical_json(packet).encode()
                else:
                    transport = verb.startswith("transport_")
                    host = (
                        "elasticsearch"
                        if verb.startswith("guest_dns_")
                        else c.observation.original_ipv4
                    )
                    route = (
                        "/_nodes/settings,http,transport,remote_cluster_server,jvm?flat_settings=true"
                        if verb == "nodes_info"
                        else "/_cluster/state/master_node,nodes"
                        if verb == "identity_state"
                        else "/_security/_authenticate"
                    )
                    replacements = {
                        "PURPOSE": purpose.value,
                        "LEAF": manifest[
                            "transport_leaf_der_sha256" if transport else "http_leaf_der_sha256"
                        ],
                        "CA": base64.b64encode(material[5] if transport else material[2]).decode(),
                        "KEY": base64.b64encode(
                            material[3] if verb == "transport_certificate" else b""
                        ).decode(),
                        "CERT": base64.b64encode(
                            material[4] if verb == "transport_certificate" else b""
                        ).decode(),
                        "CLIENT": "true" if verb == "transport_certificate" else "false",
                        "TRANSPORT": "true" if transport else "false",
                        "HOST": host,
                        "ROUTE": route,
                        "AUTH": authorization,
                    }
                    source = _JAVA_TEMPLATE
                    for name, text in replacements.items():
                        source = source.replace("<" + name + ">", text)
                    if any("<" + name + ">" in source for name in replacements):
                        raise _denied()
                    argv = (
                        *original,
                        "exec",
                        "--interactive",
                        c.final.container_id,
                        *_JAVA_PREFIX,
                        *_JAVA_FLAGS,
                        "--source",
                        "21",
                        "/dev/stdin",
                    )
                    private = source.encode()
            if private is not None and len(private) > 65536:
                raise _denied()
            value = RouteCommand(purpose, argv, private)
            self._commands[value] = _freeze(value)
            self._purposes.add(purpose)
            return value
        except Exception:
            raise _denied() from None

    def assert_command(self, command: RouteCommand) -> None:
        try:
            self._runtime()
            if type(command) is not RouteCommand or self._commands.get(command) != _freeze(command):
                raise _denied()
        except Exception:
            raise _denied() from None

    def decode(self, command: RouteCommand, response: PrivateRouteResponse) -> DecodedRouteProbe:
        try:
            self.assert_command(command)
            if (
                type(response) is not PrivateRouteResponse
                or type(response.exit_code) is not int
                or response.exit_code != 0
                or type(response.stdout) is not bytes
                or type(response.stderr) is not bytes
                or response.stderr != b""
                or not 0 < len(response.stdout) <= 1024 * 1024
            ):
                raise _denied()
            signature = _freeze(response)
            if command in self._decoded:
                old, decoded_signature, cached = self._decoded[command]
                if old != signature or decoded_signature != _freeze(cached):
                    raise _denied()
                return cached
            purpose, verb = (
                command.purpose,
                command.purpose.value.removesuffix("_before").removesuffix("_after"),
            )
            metadata = {
                "daemon_id",
                "container",
                "image",
                "volume",
                "network",
                "all_ids",
                "security_config",
            }
            public: dict[str, Any]
            if verb in metadata:
                body, public = (
                    response.stdout,
                    {"schema_version": 1, "purpose": purpose.value, "code": "recorded_metadata"},
                )
            else:
                manifest = _load(cast(Any, self.context.tls_assets).manifest_json.encode())
                binding = self._runtime()
                key = next(key for key in binding.keys if key.role == "collector")
                body, public = _decode_wire(
                    purpose,
                    response.stdout,
                    manifest[
                        "transport_leaf_der_sha256"
                        if verb.startswith("transport_")
                        else "http_leaf_der_sha256"
                    ],
                    key.key_id,
                    key.name,
                )
            decoded = DecodedRouteProbe(purpose, body, canonical_json(public))
            self._decoded[command] = signature, _freeze(decoded), decoded
            self.assert_command(command)
            return decoded
        except Exception:
            raise _denied() from None

    def _assemble(
        self,
        start_action: ReservedCutoverAction,
        probes: tuple[DecodedRouteProbe, ...],
        observed_at: datetime,
        sample_started_at: datetime,
        sample_finished_at: datetime,
    ) -> tuple[tuple[RouteObservation, ...], str]:
        """Structural assembly; only the recorded issuer can issue final authority."""
        self._runtime()
        if type(probes) is not tuple or len(probes) != 27:
            raise _denied()
        retained = {item[2]: item[1] for item in self._decoded.values()}
        if any(type(x) is not DecodedRouteProbe or retained.get(x) != _freeze(x) for x in probes):
            raise _denied()
        packet = {x.purpose: x for x in probes}
        if (
            set(packet) != set(RouteProbeKind)
            or type(observed_at) is not datetime
            or observed_at.utcoffset() != timedelta(0)
            or type(sample_started_at) is not datetime
            or type(sample_finished_at) is not datetime
            or sample_started_at.utcoffset() != timedelta(0)
            or sample_finished_at.utcoffset() != timedelta(0)
            or not sample_started_at <= sample_finished_at <= observed_at
        ):
            raise _denied()
        c = self.context
        builder, final, inventory = c.deployment, c.final, c.final_inventory
        assert builder is not None and final is not None and inventory is not None
        if start_action.action_id != final.action_id:
            raise _denied()
        public_deployment = _load(final.manifest_json.encode())
        for side in ("before", "after"):

            def raw(name: str, selected_side: str = side) -> bytes:
                return packet[RouteProbeKind(name + "_" + selected_side)].body

            current = builder.decode_daemon(
                start_action,
                RawDeploymentReadback(
                    raw("daemon_id"),
                    raw("container"),
                    raw("image"),
                    raw("volume"),
                    raw("network"),
                    raw("all_ids"),
                    builder.tls_hashes,
                    raw("security_config"),
                ),
                predecessor=c.bootstrap,
                observed_at=observed_at,
            )
            builder.assert_observed(current)
            old, new = dict(public_deployment), _load(current.manifest_json.encode())
            old.pop("observed_at")
            new.pop("observed_at")
            if old != new:
                raise _denied()
        topologies = []
        routing = []
        for side in ("before", "after"):
            info = _load(packet[RouteProbeKind("nodes_info_" + side)].body)
            state = _load(packet[RouteProbeKind("identity_state_" + side)].body)
            nodes = info.get("nodes")
            if (
                info.get("_nodes") != {"total": 1, "successful": 1, "failed": 0}
                or type(info.get("_nodes")) is not dict
                or any(type(v) is not int for v in info["_nodes"].values())
                or type(nodes) is not dict
                or set(nodes) != {inventory.topology.stable_node_id}
                or info.get("cluster_name") != inventory.topology.cluster_name
                or state.get("cluster_uuid") != inventory.topology.cluster_uuid
                or state.get("master_node") != inventory.topology.stable_node_id
                or type(state.get("nodes")) is not dict
                or set(state["nodes"]) != set(nodes)
            ):
                raise _denied()
            node = nodes[inventory.topology.stable_node_id]
            state_node = state["nodes"][inventory.topology.stable_node_id]
            if (
                type(node) is not dict
                or type(state_node) is not dict
                or state_node.get("ephemeral_id") != inventory.topology.ephemeral_id
            ):
                raise _denied()
            jvm = node.get("jvm")
            if (
                type(jvm) is not dict
                or type(jvm.get("start_time_in_millis")) is not int
                or jvm["start_time_in_millis"] <= 0
            ):
                raise _denied()
            at = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(
                milliseconds=jvm["start_time_in_millis"]
            )
            if at != inventory.topology.jvm_start_at or at > observed_at:
                raise _denied()
            settings, http, transport, roles = (
                node.get(key) for key in ("settings", "http", "transport", "roles")
            )
            if (
                any(type(x) is not dict for x in (settings, http, transport))
                or type(roles) is not list
                or any(type(x) is not str for x in roles)
                or len(roles) != len(set(roles))
            ):
                raise _denied()
            settings, http, transport = (
                cast(dict[str, Any], x) for x in (settings, http, transport)
            )
            roles = cast(list[str], roles)
            expected_roles = {
                "master",
                "data",
                "data_content",
                "data_hot",
                "data_warm",
                "data_cold",
                "data_frozen",
                "ingest",
                "ml",
                "transform",
            }
            if (
                set(roles) != expected_roles
                or "remote_cluster_server" in node
                or transport.get("profiles") != {}
            ):
                raise _denied()
            if any(
                not isinstance(key, str)
                or key.startswith(("http.profiles.", "transport.profiles."))
                for key in settings
            ):
                raise _denied()
            required = {
                "xpack.security.enabled": "true",
                "xpack.security.http.ssl.enabled": "true",
                "xpack.security.transport.ssl.enabled": "true",
                "xpack.security.transport.ssl.client_authentication": "required",
                "remote_cluster_server.enabled": "false",
            }
            if any(settings.get(name) != value for name, value in required.items()):
                raise _denied()
            for slot, port in ((http, 9200), (transport, 9300)):
                addresses = slot.get("bound_address")
                if (
                    type(addresses) is not list
                    or not addresses
                    or any(type(x) is not str for x in addresses)
                    or len(addresses) != len(set(addresses))
                    or not set(addresses) <= {f"0.0.0.0:{port}", f"[::]:{port}"}
                    or slot.get("publish_address")
                    not in {
                        f"{c.observation.original_ipv4}:{port}",
                        f"elasticsearch/{c.observation.original_ipv4}:{port}",
                    }
                ):
                    raise _denied()
            topologies.append((inventory.topology.stable_node_id, state_node["ephemeral_id"], at))
            routing.append(
                canonical_json(
                    {"settings": settings, "http": http, "transport": transport, "roles": roles}
                )
            )
        if topologies[0] != topologies[1] or routing[0] != routing[1]:
            raise _denied()
        public = {
            purpose.value: _load(probe.public_json.encode()) for purpose, probe in packet.items()
        }
        # Complete deployment decoder above supplies actual network/config exclusion;
        # only this closed public projection is hashed, never raw node settings.
        profile = {
            "kind": "single_secure_listener_profile",
            "http_port": 9200,
            "transport_port": 9300,
            "http_profiles": "absent",
            "transport_profiles": "absent",
            "remote_cluster_server": "disabled",
            "remote_cluster_client": "absent",
            "deployment_manifest": hashlib.sha256(final.manifest_json.encode()).hexdigest(),
        }
        app = c.app_retirement
        assert app is not None
        relay = {
            "kind": "trusted_maintenance_no_registered_credential_relay",
            "retirement_manifest": hashlib.sha256(app.manifest_json.encode()).hexdigest(),
            "deployment_manifest": profile["deployment_manifest"],
        }
        evidence: dict[str, object] = {
            "host_http": [public["host_auth"], public["host_wrong_ca"]],
            "guest_http": [public["guest_dns_auth"], public["guest_ip_auth"]],
            "http_profiles": profile,
            "transport": [
                public["transport_certificate"],
                public["transport_no_certificate"],
                profile,
            ],
            "remote_cluster": profile,
            "relay": relay,
            "anonymous": [
                public["host_anonymous"],
                public["guest_dns_anonymous"],
                public["guest_ip_anonymous"],
            ],
        }
        routes = _route_observations(evidence)
        manifest = canonical_json(
            {
                "schema_version": 1,
                "kind": "native_seven_routes",
                "issued_at": observed_at.isoformat(timespec="microseconds"),
                "sample_started_at": sample_started_at.isoformat(timespec="microseconds"),
                "sample_finished_at": sample_finished_at.isoformat(timespec="microseconds"),
                "final_container_id": final.container_id,
                "epoch_id": builder.epoch.binding.access_epoch_id,
                "execution_id": str(final.execution_id),
                "stable_node_id": inventory.topology.stable_node_id,
                "ephemeral_id": inventory.topology.ephemeral_id,
                "jvm_start_at": inventory.topology.jvm_start_at.isoformat(timespec="microseconds"),
                "template_sha256": _ROUTE_TEMPLATE_DIGEST,
                "routes": {
                    row.name: {
                        "disposition": row.disposition,
                        "tls_verified": row.tls_verified,
                        "authentication_verified": row.authentication_verified,
                        "client_certificate_required": row.client_certificate_required,
                        "evidence_sha256": row.evidence_sha256,
                    }
                    for row in routes
                },
            }
        )
        return routes, manifest
