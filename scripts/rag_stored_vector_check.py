"""One public synthetic stored-vector comparison; never an index-wide compatibility proof.

Run with the approved Conda interpreter from the repository root. Importing this
module performs no network, database, model, or filesystem work. Runtime admission
uses the existing application checks; only the stored-vector reads use this GET client.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import re
import ssl
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "backend/tests/fixtures/rag/stored_payment_table.json"
MODEL = ROOT / "model-profiles/rag/models/multilingual-e5-base-v1.yaml"
TEXT_SHA = "a1c7da4b3b5cef936711abe21dc6cf856af352e14db649b1f61f9512b0d8dcb2"
REVISION = "d128750597153bb5987e10b1c3493a34e5a4502a"
IDENTITIES = {
    "chunk_id": "d5f55bda-d34e-4dba-9ce7-04d96083e71d",
    "document_id": "aa69ddec-f57f-40dd-bc04-c290d0646cf4",
    "asset_version_id": "9e7c269b-0717-4946-8ac8-765f190ca8d0",
    "projection_id": "4d5bd2e6-4b22-48cc-a516-b26e512012d2",
    "index_build_id": "6f9d9039-76d2-4ae2-add6-1cd811cd1adf",
    "indexing_profile_id": "00000000-0000-0000-0000-000000000201",
    "asset_sha256": "fc303d64b9c33a1049b97468b48f69f6135d07c69e6026ae10072581479c7723",
}
INDEX = (
    "ai-workshop-local-clean-rag-00000000-0000-0000-0000-000000000201-"
    "6f9d9039-76d2-4ae2-add6-1cd811cd1adf"
)
EXPECTED_MODEL = {
    "repo_id": "intfloat/multilingual-e5-base",
    "revision": REVISION,
    "dimension": 768,
    "max_tokens": 512,
    "query_prefix": "query: ",
    "document_prefix": "passage: ",
    "normalize": True,
    "device": "cpu",
    "dtype": "float32",
    "output_mode": "dense",
    "data_policy": "local_only",
}


class CheckFailure(Exception):
    """A fixed, credential-free operator error code."""


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def validate_fixture(fixture: dict[str, Any]) -> None:
    if (
        any(fixture.get(key) != value for key, value in IDENTITIES.items())
        or fixture.get("index_name") != INDEX
        or digest(str(fixture.get("chunk_text", "")).encode()) != TEXT_SHA
        or fixture.get("workspace", {}).get("id")
        != "2292dfa0-3af8-4494-a8ce-da03ef2aa6ed"
    ):
        raise CheckFailure("fixture_drift")


def validate_source(source: dict[str, Any], fixture: dict[str, Any]) -> list[float]:
    validate_fixture(fixture)
    for key in (
        "chunk_id",
        "asset_version_id",
        "projection_id",
        "index_build_id",
        "indexing_profile_id",
    ):
        if source.get(key) != fixture[key]:
            raise CheckFailure("source_drift")
    # These two fields are not present in the current IndexDocument schema.
    for key in ("document_id", "asset_sha256"):
        if key in source and source[key] != fixture[key]:
            raise CheckFailure("source_drift")
    if source.get("text") != fixture["chunk_text"]:
        raise CheckFailure("source_drift")
    return validated_vector(source.get("embedding"))


def validated_vector(value: object) -> list[float]:
    if not isinstance(value, list) or len(value) != 768:
        raise CheckFailure("vector_invalid")
    if any(type(item) not in (int, float) or not math.isfinite(item) for item in value):
        raise CheckFailure("vector_invalid")
    values = [float(item) for item in value]
    norm = math.sqrt(sum(item * item for item in values))
    if abs(norm - 1.0) > 1e-5:
        raise CheckFailure("vector_invalid")
    return values


def compare_vectors(stored: object, current: object) -> dict[str, object]:
    left, right = validated_vector(stored), validated_vector(current)
    left_norm = math.sqrt(sum(item * item for item in left))
    right_norm = math.sqrt(sum(item * item for item in right))
    cosine = sum(a * b for a, b in zip(left, right, strict=True)) / (
        left_norm * right_norm
    )
    error = max(abs(a - b) for a, b in zip(left, right, strict=True))
    return {
        "dimension": 768,
        "stored_norm": left_norm,
        "current_norm": right_norm,
        "cosine": cosine,
        "max_absolute_error": error,
        "compatible": cosine >= 0.99999 and error <= 1e-5,
    }


def validate_endpoint(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme not in ("http", "https")
        or parsed.hostname not in ("127.0.0.1", "localhost", "::1")
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or parsed.port is None
    ):
        raise CheckFailure("endpoint_invalid")


def read_stored(
    client: httpx.Client,
    fixture: dict[str, Any],
    model: dict[str, Any],
) -> list[float]:
    """Two exact GETs. No search, mutation, redirect, or alternate source fallback."""
    validate_fixture(fixture)
    try:
        response = client.get(f"/{INDEX}/_mapping")
        if response.status_code != 200:
            raise CheckFailure("es_read_failed")
        mapping = response.json()[INDEX]["mappings"]
        meta = mapping["_meta"]["rag"]
        for key in ("index_build_id", "projection_id", "indexing_profile_id"):
            if meta.get(key) != fixture[key]:
                raise CheckFailure("index_metadata_drift")
        if meta.get("vector_dimension") != 768:
            raise CheckFailure("index_metadata_drift")
        field = mapping["properties"]["embedding"]
        if field.get("type") != "dense_vector" or field.get("dims") != 768:
            raise CheckFailure("index_metadata_drift")
        if field.get("similarity") != "cosine":
            raise CheckFailure("index_metadata_drift")
        for key in ("revision", "model_revision"):
            if key in meta and meta[key] != model["revision"]:
                raise CheckFailure("index_metadata_drift")
        response = client.get(
            f"/{INDEX}/_doc/{fixture['chunk_id']}",
            params={"_source_exclude_vectors": "false"},
        )
        if response.status_code != 200:
            raise CheckFailure("es_read_failed")
        document = response.json()
        if (
            document.get("_index") != INDEX
            or document.get("_id") != fixture["chunk_id"]
            or document.get("found") is not True
        ):
            raise CheckFailure("source_drift")
        source = document["_source"]
        if source.get("workspace_id") != fixture["workspace"]["id"]:
            raise CheckFailure("source_drift")
        return validate_source(source, fixture)
    except CheckFailure:
        raise
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        raise CheckFailure("es_read_failed") from None


def load_plan(
    session: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    import yaml

    raw = (session / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    if (
        manifest.get("schema_version") != 1
        or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", str(manifest.get("session_id", ""))
        )
        or Path(manifest["target_prefix"]).resolve() != Path(sys.prefix).resolve()
        or Path(sys.executable).resolve()
        != (Path(manifest["target_prefix"]) / "python.exe").resolve()
        or sys.flags.optimize != 0
        or not (Path(sys.prefix) / "conda-meta").is_dir()
    ):
        raise CheckFailure("manifest_invalid")
    fixture_raw, model_raw = FIXTURE.read_bytes(), MODEL.read_bytes()
    if (
        digest(fixture_raw) != manifest["fixture_sha256"]
        or digest(model_raw) != manifest["model_yaml_sha256"]
    ):
        raise CheckFailure("manifest_drift")
    fixture = json.loads(fixture_raw)
    validate_fixture(fixture)
    definition = yaml.safe_load(model_raw)
    model = definition["config"]
    if (
        definition.get("id") != "00000000-0000-0000-0000-000000000101"
        or model != EXPECTED_MODEL
    ):
        raise CheckFailure("model_drift")
    cache = Path(manifest["model_cache_root"])
    snapshot = cache / "models--intfloat--multilingual-e5-base" / "snapshots" / REVISION
    if not cache.is_absolute() or not snapshot.is_dir():
        raise CheckFailure("model_cache_missing")
    return manifest, fixture, model, digest(raw)


def runtime_client(settings: Any) -> httpx.Client:
    """Same settings, capability and explicit CA rules as the application ES factory."""
    from ai_workshop.labs.rag.indexing.access_epoch_runtime import require_launch_role

    validate_endpoint(settings.elasticsearch_url)
    require_launch_role(settings, writer=False)
    headers: dict[str, str] = {}
    verify: ssl.SSLContext | bool = True
    if settings.elasticsearch_access_epoch_id is not None:
        if (
            settings.elasticsearch_api_key is None
            or settings.elasticsearch_role is None
            or settings.elasticsearch_ca_certs is None
            or not settings.elasticsearch_url.startswith("https://")
        ):
            raise CheckFailure("credential_unavailable")
        verify = ssl.create_default_context(cafile=str(settings.elasticsearch_ca_certs))
        verify.check_hostname = True
        verify.verify_mode = ssl.CERT_REQUIRED
        headers["Authorization"] = (
            "ApiKey " + settings.elasticsearch_api_key.get_secret_value()
        )
    return httpx.Client(
        base_url=settings.elasticsearch_url,
        headers=headers,
        transport=httpx.HTTPTransport(retries=0, verify=verify, trust_env=False),
        trust_env=False,
        follow_redirects=False,
        timeout=30,
    )


def write_result(session: Path, result: dict[str, Any]) -> None:
    with (session / "vector-result.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=True, allow_nan=False, indent=2)
        stream.write("\n")


def execute_runtime(
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    model: dict[str, Any],
) -> dict[str, object]:
    # Standalone launch also works when dependencies were installed without the project.
    # These changes affect this operator process only, never the caller or user profile.
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "backend/src"))
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.embeddings.contracts import EmbeddingModelConfig
    from ai_workshop.labs.rag.embeddings.sentence_transformers import (
        SentenceTransformerEmbedding,
    )
    from ai_workshop.labs.rag.indexing.access_epoch_runtime import (
        verify_original_runtime,
    )
    from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy

    settings = Settings()
    if settings.environment != "local":
        raise CheckFailure("environment_invalid")
    configure_windows_selector_policy()
    asyncio.run(verify_original_runtime(settings, writer=False, non_es=False))
    with runtime_client(settings) as client:
        stored = read_stored(client, fixture, model)
    embedding = SentenceTransformerEmbedding(
        EmbeddingModelConfig(**model, batch_size=32),
        cache_folder=Path(manifest["model_cache_root"]),
        local_files_only=True,
    )
    try:
        if embedding.count_tokens(fixture["chunk_text"]) > model["max_tokens"]:
            raise CheckFailure("input_tokens_exceeded")
        current = embedding.encode_documents([fixture["chunk_text"]])
        if len(current) != 1:
            raise CheckFailure("vector_invalid")
        return compare_vectors(stored, current[0])
    finally:
        embedding.close()


def run(session: Path) -> int:
    result: dict[str, Any] = {"status": "failed", "sample_count": 1}
    try:
        manifest, fixture, model, manifest_sha = load_plan(session)
        result.update(
            session_id=manifest["session_id"],
            manifest_sha256=manifest_sha,
            fixture_sha256=manifest["fixture_sha256"],
            model_yaml_sha256=manifest["model_yaml_sha256"],
            target_prefix=manifest["target_prefix"],
            model_cache_root=manifest["model_cache_root"],
            identity_sha256=digest(json.dumps(IDENTITIES, sort_keys=True).encode()),
        )
        if (session / "vector-result.json").exists():
            raise CheckFailure("session_already_used")
        with (session / "vector-started.json").open("x", encoding="utf-8") as stream:
            json.dump(
                {"session_id": manifest["session_id"], "manifest_sha256": manifest_sha},
                stream,
            )
        metrics = execute_runtime(manifest, fixture, model)
        result.update(
            metrics=metrics, status="passed" if metrics["compatible"] else "failed"
        )
        if not metrics["compatible"]:
            result["code"] = "vector_incompatible"
    except CheckFailure as exc:
        result["code"] = str(exc)
    except FileExistsError:
        result["code"] = "session_already_used"
    except Exception:  # noqa: BLE001 - operator boundary must not print model/credential details.
        result["code"] = "vector_check_failed"
    result["checked_at"] = datetime.now(UTC).isoformat()
    try:
        write_result(session, result)
    except (OSError, ValueError):
        print("vector_result_write_failed")
        return 1
    print("vector_check_passed" if result["status"] == "passed" else result["code"])
    return 0 if result["status"] == "passed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    args = parser.parse_args()
    return run(args.session.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
