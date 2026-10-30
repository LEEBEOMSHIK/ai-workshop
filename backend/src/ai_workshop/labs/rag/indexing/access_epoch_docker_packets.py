"""Join five bounded Docker packets to guarded original/deployment facts.

Pure selected-field validation only. Raw inspect metadata never becomes public
evidence, and callers retain responsibility for provenance and current phase.
"""

import json
import math
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    DeploymentError,
    RuntimeDeployment,
    verify_runtime_deployment,
)
from ai_workshop.labs.rag.indexing.access_epoch_native import original_image_reference
from ai_workshop.labs.rag.indexing.access_epoch_types import canonical_json
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import CONTEXT_ENDPOINT_DIGEST

_LIMIT = 2 * 1024 * 1024
_HASHES = (
    "http_ca_sha256",
    "transport_ca_sha256",
    "http_ca_der_sha256",
    "transport_ca_der_sha256",
    "http_leaf_der_sha256",
    "transport_leaf_der_sha256",
)


def _denied() -> DeploymentError:
    return DeploymentError("secured_docker_packet_denied")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _denied()
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise _denied()


def _float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise _denied()
    return number


def _decode(body: bytes, *, inspect: bool = False) -> dict[str, Any]:
    if type(body) is not bytes or not 0 < len(body) <= _LIMIT:
        raise _denied()
    value = json.loads(
        body.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float
    )
    if inspect:
        if type(value) is not list or len(value) != 1:
            raise _denied()
        value = value[0]
    if type(value) is not dict:
        raise _denied()
    return value


def validate_docker_identity(
    daemon_body: bytes,
    container_body: bytes,
    network_body: bytes,
    image_body: bytes,
    volume_body: bytes,
    *,
    deployment_manifest_json: str,
    original_image_json: str,
    original_volume_json: str,
    secured_config: bytes,
    tls_public_hashes: dict[str, str],
) -> RuntimeDeployment:
    try:
        daemon = _decode(daemon_body)
        for body in (container_body, network_body):
            _decode(body, inspect=True)
        image, volume = _decode(image_body, inspect=True), _decode(volume_body, inspect=True)
        manifests = (deployment_manifest_json, original_image_json, original_volume_json)
        if any(type(raw) is not str for raw in manifests):
            raise _denied()
        deployed, original_image, original_volume = (_decode(raw.encode()) for raw in manifests)
        if type(tls_public_hashes) is not dict or set(tls_public_hashes) != set(_HASHES):
            raise _denied()
        current = verify_runtime_deployment(
            deployment_manifest_json,
            daemon=daemon_body,
            container=container_body,
            network=network_body,
            secured_config=secured_config,
            tls_public_hashes=tuple(tls_public_hashes[name] for name in _HASHES),
        )
        reference = original_image_reference(
            {
                "image_id": image["Id"],
                "repo_digests": image["RepoDigests"],
                "os": image["Os"],
                "architecture": image["Architecture"],
            }
        )
        image_public: dict[str, object] = {
            "image_id": reference.image_id,
            "manifest_digest": reference.manifest_digest,
            "architecture": reference.architecture,
        }
        if canonical_json(original_image) != canonical_json(image_public) or (
            reference.image_id != deployed["image_id"]
            or reference.manifest_digest != deployed["manifest_digest"]
        ):
            raise _denied()
        name = "ai-workshop_elasticsearch-data"
        if (
            volume["Name"] != name
            or volume["Driver"] != "local"
            or volume["Scope"] != "local"
            or volume["Options"] is not None
            or volume["Mountpoint"] != f"/var/lib/docker/volumes/{name}/_data"
            or type(volume["CreatedAt"]) is not str
        ):
            raise _denied()
        created = datetime.fromisoformat(volume["CreatedAt"])
        if created.utcoffset() != timedelta(0) or created > current.started_at:
            raise _denied()
        daemon_sha = sha256(
            canonical_json(
                {
                    "id": daemon["ID"],
                    "os": daemon["OSType"],
                    "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST,
                }
            ).encode()
        ).hexdigest()
        volume_public = {
            "name": volume["Name"],
            "driver": volume["Driver"],
            "scope": volume["Scope"],
            "created_at": volume["CreatedAt"],
            "mountpoint": volume["Mountpoint"],
            "options": None,
            "daemon_sha256": daemon_sha,
        }
        if canonical_json(original_volume) != canonical_json(volume_public):
            raise _denied()
        return current
    except Exception:
        raise _denied() from None
