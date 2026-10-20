"""Offline contracts for the one-sample stored E5 compatibility operator."""

import importlib.util
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[3]


def test_operator_entry_point_exists() -> None:
    assert (ROOT / "scripts/rag_stored_vector_check.py").is_file()


@pytest.fixture
def tool() -> ModuleType:
    source = ROOT / "scripts/rag_stored_vector_check.py"
    assert source.exists(), "The read-only vector compatibility tool is not implemented"
    spec = importlib.util.spec_from_file_location("stored_vector_operator", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fixture() -> dict[str, Any]:
    value: dict[str, Any] = json.loads(
        (ROOT / "backend/tests/fixtures/rag/stored_payment_table.json").read_text(encoding="utf-8")
    )
    return value


def test_identical_vector_returns_metrics_without_raw_values(tool: ModuleType) -> None:
    vector = [1.0] + [0.0] * 767
    result = tool.compare_vectors(vector, vector)
    assert result == {
        "dimension": 768,
        "stored_norm": 1.0,
        "current_norm": 1.0,
        "cosine": 1.0,
        "max_absolute_error": 0.0,
        "compatible": True,
    }


@pytest.mark.parametrize(
    "bad", [[1.0], [0.0] * 768, [math.nan] * 768, [math.inf] * 768, [True] * 768, ["1"] * 768]
)
def test_invalid_vectors_are_rejected(tool: ModuleType, bad: list[object]) -> None:
    with pytest.raises(tool.CheckFailure, match="vector_invalid"):
        tool.compare_vectors([1.0] + [0.0] * 767, bad)


def test_small_rotation_fails_absolute_error_even_with_high_cosine(tool: ModuleType) -> None:
    angle = 0.00002
    current = [math.cos(angle), math.sin(angle)] + [0.0] * 766
    result = tool.compare_vectors([1.0] + [0.0] * 767, current)
    assert result["cosine"] > 0.99999
    assert result["compatible"] is False


def test_source_drift_is_rejected_before_encoding(
    tool: ModuleType,
    fixture: dict[str, Any],
) -> None:
    source = {**fixture, "text": fixture["chunk_text"], "embedding": [1.0] + [0.0] * 767}
    source["asset_version_id"] = "other"
    with pytest.raises(tool.CheckFailure, match="source_drift"):
        tool.validate_source(source, fixture)


def test_source_accepts_only_exact_synthetic_text(
    tool: ModuleType,
    fixture: dict[str, Any],
) -> None:
    source = {**fixture, "text": fixture["chunk_text"], "embedding": [1.0] + [0.0] * 767}
    assert tool.validate_source(source, fixture) == source["embedding"]
    source["text"] += "private material"
    with pytest.raises(tool.CheckFailure, match="source_drift"):
        tool.validate_source(source, fixture)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:9200",
        "http://user:secret@127.0.0.1:9200",
        "http://127.0.0.1:9200/path",
        "http://127.0.0.1:9200?secret=1",
    ],
)
def test_endpoint_rejects_external_or_credential_urls(tool: ModuleType, url: str) -> None:
    with pytest.raises(tool.CheckFailure, match="endpoint_invalid"):
        tool.validate_endpoint(url)


def test_es_reader_only_issues_two_gets_and_does_not_follow_redirects(
    tool: ModuleType,
    fixture: dict[str, Any],
) -> None:
    seen: list[tuple[str, str]] = []

    def response(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(302, headers={"Location": "http://example.com/private"})

    with (
        httpx.Client(
            base_url="http://127.0.0.1:9200",
            transport=httpx.MockTransport(response),
            follow_redirects=False,
        ) as client,
        pytest.raises(tool.CheckFailure, match="es_read_failed"),
    ):
        tool.read_stored(client, fixture, {})
    assert len(seen) == 1
    assert seen[0][0] == "GET"


def test_result_is_exclusive_and_contains_no_source_material(
    tool: ModuleType,
    tmp_path: Path,
) -> None:
    tool.write_result(tmp_path, {"status": "passed", "identity_sha256": "a" * 64})
    assert json.loads((tmp_path / "vector-result.json").read_text())["status"] == "passed"
    with pytest.raises(FileExistsError):
        tool.write_result(tmp_path, {"status": "failed"})


def test_import_does_not_load_model_runtime(tool: ModuleType) -> None:
    assert "SentenceTransformerEmbedding" not in vars(tool)


def test_fixture_identity_is_pinned(tool: ModuleType, fixture: dict[str, Any]) -> None:
    tool.validate_fixture(fixture)
    fixture["chunk_id"] = "another"
    with pytest.raises(tool.CheckFailure, match="fixture_drift"):
        tool.validate_fixture(fixture)


@pytest.fixture
def session(tool: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    prefix = tmp_path / "existing-prefix"
    (prefix / "conda-meta").mkdir(parents=True)
    monkeypatch.setattr(tool.sys, "prefix", str(prefix))
    monkeypatch.setattr(tool.sys, "executable", str(prefix / "python.exe"))
    cache = tmp_path / "cache"
    (cache / "models--intfloat--multilingual-e5-base" / "snapshots" / tool.REVISION).mkdir(
        parents=True,
    )
    directory = tmp_path / "session"
    directory.mkdir()
    (directory / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "offline-only",
                "target_prefix": str(prefix),
                "fixture_sha256": tool.digest(tool.FIXTURE.read_bytes()),
                "model_yaml_sha256": tool.digest(tool.MODEL.read_bytes()),
                "model_cache_root": str(cache),
            }
        ),
        encoding="utf-8",
    )
    return directory


@pytest.mark.parametrize(
    "field,value",
    [
        ("target_prefix", "C:/different-prefix"),
        ("fixture_sha256", "0" * 64),
        ("model_yaml_sha256", "0" * 64),
        ("schema_version", 2),
        ("session_id", "../escape"),
    ],
)
def test_plan_drift_prevents_runtime(
    tool: ModuleType,
    session: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
) -> None:
    path = session / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest[field] = value
    path.write_text(json.dumps(manifest))

    def forbidden(*args: object) -> None:
        pytest.fail("Drift must stop before admission, sockets or model loading")

    monkeypatch.setattr(tool, "execute_runtime", forbidden)
    assert tool.run(session) == 1
    assert not (session / "vector-started.json").exists()
    assert json.loads((session / "vector-result.json").read_text())["status"] == "failed"


def test_single_session_success_and_repeat_preserve_evidence(
    tool: ModuleType,
    session: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vector = [1.0] + [0.0] * 767
    monkeypatch.setattr(tool, "execute_runtime", lambda *_: tool.compare_vectors(vector, vector))
    assert tool.run(session) == 0
    result = (session / "vector-result.json").read_bytes()
    data = json.loads(result)
    assert data["session_id"] == "offline-only"
    assert data["manifest_sha256"] == tool.digest((session / "manifest.json").read_bytes())
    assert data["sample_count"] == 1
    manifest = json.loads((session / "manifest.json").read_text())
    assert data["target_prefix"] == manifest["target_prefix"]
    assert data["model_cache_root"] == manifest["model_cache_root"]
    assert datetime.fromisoformat(data["checked_at"]).utcoffset() == UTC.utcoffset(None)
    assert "chunk_text" not in data and "embedding" not in data

    def forbidden(*args: object) -> None:
        pytest.fail("A second run must not execute the runtime")

    monkeypatch.setattr(tool, "execute_runtime", forbidden)
    assert tool.run(session) == 1
    assert (session / "vector-result.json").read_bytes() == result


def test_runtime_error_is_sanitized_and_reservation_remains(
    tool: ModuleType,
    session: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail(*args: object) -> None:
        raise RuntimeError("secret-api-key and private document text")

    monkeypatch.setattr(tool, "execute_runtime", fail)
    assert tool.run(session) == 1
    output = capsys.readouterr()
    result = (session / "vector-result.json").read_text()
    assert "secret" not in output.out + output.err + result
    assert "vector_check_failed" in result
    assert (session / "vector-started.json").exists()


@pytest.mark.parametrize("drift", [False, True])
def test_exact_metadata_and_document_gets(
    tool: ModuleType,
    fixture: dict[str, Any],
    drift: bool,
) -> None:
    requests: list[httpx.Request] = []
    vector = [1.0] + [0.0] * 767
    meta = {
        key: fixture[key]
        for key in (
            "projection_id",
            "index_build_id",
            "indexing_profile_id",
        )
    }
    meta["vector_dimension"] = 767 if drift else 768

    def response(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/_mapping"):
            return httpx.Response(
                200,
                json={
                    tool.INDEX: {
                        "mappings": {
                            "_meta": {"rag": meta},
                            "properties": {
                                "embedding": {
                                    "type": "dense_vector",
                                    "dims": 768,
                                    "similarity": "cosine",
                                }
                            },
                        }
                    }
                },
            )
        assert request.url.path == f"/{tool.INDEX}/_doc/{fixture['chunk_id']}"
        assert dict(request.url.params) == {"_source_exclude_vectors": "false"}
        source = {
            **fixture,
            "text": fixture["chunk_text"],
            "embedding": vector,
            "workspace_id": fixture["workspace"]["id"],
        }
        return httpx.Response(
            200,
            json={
                "_index": tool.INDEX,
                "_id": fixture["chunk_id"],
                "found": True,
                "_source": source,
            },
        )

    with httpx.Client(
        base_url="http://127.0.0.1:9200",
        transport=httpx.MockTransport(response),
        follow_redirects=False,
    ) as client:
        if drift:
            with pytest.raises(tool.CheckFailure, match="index_metadata_drift"):
                tool.read_stored(client, fixture, tool.EXPECTED_MODEL)
        else:
            assert tool.read_stored(client, fixture, tool.EXPECTED_MODEL) == vector
    assert len(requests) == (1 if drift else 2)
    assert all(request.method == "GET" for request in requests)


def test_transport_retains_role_check_and_disables_retries_proxy_redirects(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = ModuleType("ai_workshop.labs.rag.indexing.access_epoch_runtime")
    seen: dict[str, Any] = {}

    def role(settings: object, *, writer: bool) -> None:
        seen["writer"] = writer

    admission.require_launch_role = role  # type: ignore[attr-defined]
    monkeypatch.setitem(tool.sys.modules, admission.__name__, admission)

    def transport(**kwargs: Any) -> object:
        seen["transport"] = kwargs
        return object()

    def client(**kwargs: Any) -> object:
        seen["client"] = kwargs
        return object()

    monkeypatch.setattr(tool.httpx, "HTTPTransport", transport)
    monkeypatch.setattr(tool.httpx, "Client", client)
    tool.runtime_client(
        SimpleNamespace(
            elasticsearch_url="http://127.0.0.1:19200",
            elasticsearch_access_epoch_id=None,
        )
    )
    assert seen["writer"] is False
    assert seen["transport"]["retries"] == 0
    assert seen["transport"]["trust_env"] is False
    assert seen["client"]["trust_env"] is False
    assert seen["client"]["follow_redirects"] is False


def test_missing_secured_credential_never_constructs_transport(
    tool: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admission = ModuleType("ai_workshop.labs.rag.indexing.access_epoch_runtime")
    admission.require_launch_role = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    monkeypatch.setitem(tool.sys.modules, admission.__name__, admission)

    def forbidden(**kwargs: Any) -> None:
        pytest.fail("Missing credential must not reach transport")

    monkeypatch.setattr(tool.httpx, "HTTPTransport", forbidden)
    with pytest.raises(tool.CheckFailure, match="credential_unavailable"):
        tool.runtime_client(
            SimpleNamespace(
                elasticsearch_url="https://127.0.0.1:9200",
                elasticsearch_access_epoch_id="epoch",
                elasticsearch_api_key=None,
                elasticsearch_role="reader",
                elasticsearch_ca_certs=None,
            )
        )


def test_wrong_executable_is_rejected_even_when_prefix_matches(
    tool: ModuleType,
    session: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tool.sys, "executable", "C:/other/python.exe")
    with pytest.raises(tool.CheckFailure, match="manifest_invalid"):
        tool.load_plan(session)


def test_optimized_interpreter_is_rejected(
    tool: ModuleType,
    session: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags = {
        key: getattr(tool.sys.flags, key)
        for key in dir(tool.sys.flags)
        if not key.startswith("_") and isinstance(getattr(tool.sys.flags, key), int)
    }
    flags["optimize"] = 1
    monkeypatch.setattr(tool.sys, "flags", SimpleNamespace(**flags))
    with pytest.raises(tool.CheckFailure, match="manifest_invalid"):
        tool.load_plan(session)


def test_runtime_prepares_project_and_offline_process_before_application_import(
    tool: ModuleType,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    class ImportReached(Exception):
        pass

    module = ModuleType("ai_workshop.config")

    def lookup(name: str) -> object:
        if name != "Settings":
            raise AttributeError(name)
        assert Path.cwd() == ROOT
        assert tool.sys.path[0] == str(ROOT / "backend/src")
        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
        raise ImportReached

    module.__getattr__ = lookup  # type: ignore[method-assign]
    monkeypatch.setitem(tool.sys.modules, module.__name__, module)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(tool.sys, "path", list(tool.sys.path))
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "0")
    with pytest.raises(ImportReached):
        tool.execute_runtime({}, {}, {})
