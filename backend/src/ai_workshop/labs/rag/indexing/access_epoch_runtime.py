"""Production floor reads and startup checks, without any cutover mutation."""

import asyncio
import hashlib
import json
import os
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from sqlalchemy import text

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.credential_store_windows import (
    WindowsCredentialStore,
    identity_from_json,
)
from ai_workshop.infrastructure.local.service_bootstrap_context import current_verified_launch
from ai_workshop.infrastructure.local.windows_private_state import NativeWindowsPrivateState
from ai_workshop.infrastructure.search.access_credentials import (
    AccessCredentialError,
    SecuredStoreIdentity,
)
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.indexing.access_epoch_admission import AccessEpochAdmission
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    verify_runtime_deployment,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE, NETWORK
from ai_workshop.shared.db import create_engine


class OriginalRuntimeAdmission:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.proof: dict[str, object] | None = None
        self.manifests: dict[str, str] | None = None
        self.floor: SecuredStoreIdentity | None = None

    async def load(self, settings: Settings) -> tuple[SecuredStoreIdentity | None, bool]:
        engine = create_engine(settings)
        try:
            async with engine.connect() as connection:
                installed = await connection.scalar(text("SELECT to_regclass('rag_access_epochs')"))
                if installed is None:
                    return None, False
                rows = (
                    (
                        await connection.execute(
                            text("""
SELECT e.store_id,e.phase,e.verified,e.manifests,f.identity
FROM rag_access_epochs e LEFT JOIN rag_access_epoch_floors f ON f.epoch_id=e.id
WHERE e.cluster_uuid=:cluster ORDER BY e.ordinal DESC LIMIT 1
"""),
                            {"cluster": settings.rag_index_cluster_uuid},
                        )
                    )
                    .mappings()
                    .all()
                )
                if not rows:
                    return None, False
                row = rows[0]
                if row["store_id"] != settings.rag_index_store_id:
                    raise AccessCredentialError("access_epoch_mismatch")
                if row["phase"] not in {"verified", "receipted"}:
                    return None, True
                if row["identity"] is None or row["verified"] is None or row["manifests"] is None:
                    raise AccessCredentialError("access_epoch_mismatch")
                value = dict(row["identity"])
                value["epoch_id"] = value.pop("access_epoch_id")
                self.floor = identity_from_json(json.dumps(value).encode())
                self.proof, self.manifests = dict(row["verified"]), dict(row["manifests"])
                return self.floor, False
        finally:
            await engine.dispose()

    def anchor(self) -> SecuredStoreIdentity | None:
        native = NativeWindowsPrivateState(self.root)
        return WindowsCredentialStore(self.root, native, native).read_floor_anchor()

    async def probe(self, settings: Settings) -> SecuredStoreIdentity:
        try:
            return await self._probe(settings)
        except Exception:
            # No native response, credential, private path or JSON parsing detail escapes.
            raise AccessCredentialError("access_epoch_mismatch") from None

    async def _probe(self, settings: Settings) -> SecuredStoreIdentity:
        floor, proof, manifests = self.floor, self.proof, self.manifests
        capability = current_verified_launch()
        if (
            floor is None
            or proof is None
            or manifests is None
            or capability is None
            or self.root != PROJECT_ROOT
            or capability.pid != os.getpid()
            or capability.epoch_id != floor.epoch_id
            or capability.ordinal != floor.ordinal
            or capability.role != settings.elasticsearch_role
            or settings.elasticsearch_access_epoch_id != floor.epoch_id
            or settings.elasticsearch_access_epoch != floor.ordinal
            or settings.elasticsearch_url
            not in {"https://127.0.0.1:9200", "https://localhost:9200"}
            or settings.elasticsearch_api_key is None
        ):
            raise AccessCredentialError("access_epoch_mismatch")
        for name, expected_digest in (
            ("new_config", floor.config_sha256),
            ("route_policy", floor.route_sha256),
            ("auth_policy", floor.auth_sha256),
        ):
            # These are already-public committed policy projections, never Docker bodies.
            if hashlib.sha256(manifests[name].encode()).hexdigest() != expected_digest:
                raise AccessCredentialError("access_epoch_mismatch")
        ca_manifest = manifests["tls_public_ca"]
        ca = json.loads(ca_manifest)
        deployment_json = manifests["new_deployment"]
        ephemeral = proof.get("new_ephemeral_id")
        if (
            type(proof.get("schema_version")) is not int
            or proof["schema_version"] != 2
            or proof.get("proof_kind") != "local_single_node_access_epoch"
            or proof.get("access_epoch_id") != str(floor.epoch_id)
            or proof.get("new_container_id") != floor.container_id
            or proof.get("cluster_uuid") != floor.cluster_uuid
            or proof.get("stable_node_id") != floor.stable_node_id
            or type(ephemeral) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", ephemeral) is None
            or proof.get("tls_public_ca_sha256") != floor.ca_sha256
            or proof.get("new_config_sha256") != floor.config_sha256
            or proof.get("route_policy_sha256") != floor.route_sha256
            or proof.get("auth_policy_sha256") != floor.auth_sha256
            or proof.get("store_id") != floor.store_id
            or type(proof.get("minimum_access_epoch")) is not int
            or proof["minimum_access_epoch"] != floor.ordinal
            or proof.get("credential_deployment_sha256")
            != hashlib.sha256(manifests["credential_deployment"].encode()).hexdigest()
            or proof.get("new_deployment_sha256")
            != hashlib.sha256(deployment_json.encode()).hexdigest()
            or hashlib.sha256(ca_manifest.encode()).hexdigest() != floor.ca_sha256
            or ca.get("epoch_id") != str(floor.epoch_id)
            or settings.elasticsearch_ca_certs is None
        ):
            raise AccessCredentialError("access_epoch_mismatch")
        actual_ca = settings.elasticsearch_ca_certs.read_bytes()
        if (
            not 0 < len(actual_ca) <= 65536
            or hashlib.sha256(actual_ca).hexdigest() != ca["http_ca_sha256"]
        ):
            raise AccessCredentialError("access_epoch_mismatch")
        directory = (
            self.root / ".local-data/access-epoch/private/tls" / str(floor.epoch_id) / "bind"
        )
        # Public certificate bytes only. Private leaf keys are never read or hashed here.
        for purpose in ("http", "transport"):
            for name, field in (("ca.crt", "ca"), ("node.crt", "leaf")):
                public = (directory / purpose / name).read_bytes()
                if not 0 < len(public) <= 65536:
                    raise AccessCredentialError("access_epoch_mismatch")
                cert = x509.load_pem_x509_certificate(public)
                if cert.fingerprint(hashes.SHA256()).hex() != ca[f"{purpose}_{field}_der_sha256"]:
                    raise AccessCredentialError("access_epoch_mismatch")
                if (
                    field == "ca"
                    and hashlib.sha256(public).hexdigest() != ca[f"{purpose}_ca_sha256"]
                ):
                    raise AccessCredentialError("access_epoch_mismatch")
        if len(floor.container_id) != 64 or any(
            ch not in "0123456789abcdef" for ch in floor.container_id
        ):
            raise AccessCredentialError("access_epoch_mismatch")

        def inspect() -> tuple[bytes, bytes, bytes]:
            # No inherited Docker context/host/plugin or Compose overrides.
            environment = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
            }
            responses = []
            for suffix in (
                ("info", "--format", "{{json .}}"),
                ("container", "inspect", floor.container_id),
                ("network", "inspect", NETWORK),
            ):
                result = subprocess.run(
                    (DOCKER_EXE, "--host", "npipe:////./pipe/dockerDesktopLinuxEngine", *suffix),
                    shell=False,
                    capture_output=True,
                    timeout=30,
                    env=environment,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode or not 0 < len(result.stdout) <= 4_194_304:
                    raise AccessCredentialError("access_epoch_mismatch")
                responses.append(result.stdout)
            return responses[0], responses[1], responses[2]

        daemon, container, network = await asyncio.to_thread(inspect)
        deployment = verify_runtime_deployment(
            deployment_json,
            daemon=daemon,
            container=container,
            network=network,
            secured_config=(
                self.root / "infrastructure/elasticsearch/elasticsearch-secured.yml"
            ).read_bytes(),
            tls_public_hashes=tuple(
                ca[k]
                for k in (
                    "http_ca_sha256",
                    "transport_ca_sha256",
                    "http_ca_der_sha256",
                    "transport_ca_der_sha256",
                    "http_leaf_der_sha256",
                    "transport_leaf_der_sha256",
                )
            ),
        )
        if (
            deployment.epoch_id != floor.epoch_id
            or deployment.container_id != floor.container_id
            or str(deployment.execution_id) != proof.get("execution_id")
        ):
            raise AccessCredentialError("access_epoch_mismatch")
        client = create_elasticsearch(settings)
        try:
            authenticated = await client.security.authenticate()
            key = authenticated.get("api_key", {})
            credentials = json.loads(manifests["credential_deployment"])
            if (
                key.get("id") != capability.key_id
                or authenticated.get("authentication_type") != "api_key"
                or credentials.get("epoch_id") != str(floor.epoch_id)
                or type(credentials.get("ordinal")) is not int
                or credentials["ordinal"] != floor.ordinal
                or credentials.get("keys", {}).get(capability.role) != capability.key_id
            ):
                raise AccessCredentialError("access_epoch_mismatch")
            root = await client.info()
            state = await client.cluster.state(metric="nodes")
            nodes = await client.nodes.info(metric="jvm")
            counts = nodes.get("_nodes", {})
            if (
                root.get("cluster_uuid") != floor.cluster_uuid
                or root.get("cluster_name") != deployment.cluster_name
                or root.get("version", {}).get("number") != "9.5.2"
                or state.get("cluster_uuid") != floor.cluster_uuid
                or state.get("master_node") != floor.stable_node_id
                or set(state.get("nodes", {})) != {floor.stable_node_id}
                or state["nodes"][floor.stable_node_id].get("ephemeral_id")
                != proof["new_ephemeral_id"]
                or nodes.get("cluster_name") != deployment.cluster_name
                or type(counts) is not dict
                or counts != {"total": 1, "successful": 1, "failed": 0}
                or any(type(v) is not int for v in counts.values())
                or set(nodes.get("nodes", {})) != {floor.stable_node_id}
            ):
                raise AccessCredentialError("access_epoch_mismatch")
            milliseconds = nodes["nodes"][floor.stable_node_id]["jvm"]["start_time_in_millis"]
            stamp = proof["new_jvm_start_at"]
            if type(milliseconds) is not int or type(stamp) is not str:
                raise AccessCredentialError("access_epoch_mismatch")
            started = datetime.fromtimestamp(milliseconds // 1000, UTC) + timedelta(
                milliseconds=milliseconds % 1000
            )
            expected = datetime.fromisoformat(stamp)
            if (
                expected.utcoffset() != timedelta(0)
                or started != expected
                or started < deployment.started_at
            ):
                raise AccessCredentialError("access_epoch_mismatch")
        finally:
            await client.close()
        return floor


async def verify_original_runtime(
    settings: Settings, *, writer: bool = False, non_es: bool = False
) -> None:
    root = Path(__file__).absolute().parents[6]
    runtime = OriginalRuntimeAdmission(root)
    await AccessEpochAdmission(runtime.load, runtime.anchor, runtime.probe).verify(
        settings, writer=writer, non_es=non_es
    )


def require_launch_role(settings: Settings, *, writer: bool = False) -> None:
    if settings.elasticsearch_access_epoch_id is None:
        return
    capability = current_verified_launch()
    if (
        capability is None
        or capability.pid != os.getpid()
        or capability.epoch_id != settings.elasticsearch_access_epoch_id
        or capability.ordinal != settings.elasticsearch_access_epoch
        or capability.role != settings.elasticsearch_role
        or writer
        and capability.role != "writer"
    ):
        raise AccessCredentialError("elasticsearch_capability_required")
