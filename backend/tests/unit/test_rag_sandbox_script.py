"""Safety checks for the persistent, synthetic-only sandbox preparation script."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "prepare_rag_sandbox.py"
spec = importlib.util.spec_from_file_location("rag_sandbox_script", SCRIPT)
assert spec and spec.loader
sandbox = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sandbox)


def test_existing_root_is_never_adopted(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="already exists"):
        sandbox.require_new_root(tmp_path)


def test_preparation_refuses_reparse_ancestor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "is_reparse", lambda path: path == tmp_path)
    with pytest.raises(ValueError, match="reparse"):
        sandbox.require_new_root(tmp_path / "new")


@pytest.mark.parametrize(
    "key,value",
    [
        ("AI_WORKSHOP_ENVIRONMENT", "production"),
        ("AI_WORKSHOP_DATABASE_URL", "postgresql+psycopg://x:y@127.0.0.1:5432/real"),
        ("AI_WORKSHOP_REDIS_URL", "redis://127.0.0.1:6379/0"),
        ("AI_WORKSHOP_OBJECT_STORE_ROOT", "C:/unrelated"),
        ("HF_HUB_OFFLINE", "0"),
    ],
)
def test_runtime_rejects_environment_outside_sandbox(tmp_path: Path, key: str, value: str) -> None:
    env = sandbox.make_environment(tmp_path, "synthetic-password", "synthetic-secret")
    env[key] = value
    with pytest.raises(ValueError, match="sandbox"):
        sandbox.validate_environment(env, tmp_path)


def test_environment_is_exactly_scoped_and_offline(tmp_path: Path) -> None:
    env = sandbox.make_environment(tmp_path, "synthetic-password", "synthetic-secret")
    sandbox.validate_environment(env, tmp_path)
    assert env["AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX"] == "ai-workshop-rag-sandbox"
    assert env["TRANSFORMERS_OFFLINE"] == "1"


@pytest.mark.parametrize("kind", ["container", "volume", "network"])
def test_existing_docker_project_resources_are_not_adopted(
    monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    monkeypatch.setattr(
        sandbox,
        "docker_names",
        lambda selected: [sandbox.PROJECT + "_postgres-data"] if selected == kind else [],
    )
    with pytest.raises(ValueError, match="existing Docker"):
        sandbox.require_fresh_docker_project()


@pytest.mark.parametrize(
    "key,value",
    [
        ("AI_WORKSHOP_PUBLISHING_PUBLIC_STORE_PATH", "C:/development/public.sqlite3"),
        ("AI_WORKSHOP_PUBLISHING_DELIVERY_MODE", "local"),
        ("AI_WORKSHOP_PROVIDER_ENDPOINT_REFS", '{"remote":"https://example.test"}'),
        ("AI_WORKSHOP_PROVIDER_SECRET_REFS", '{"key":"synthetic-hostile"}'),
        ("AI_WORKSHOP_CODEX_RUNNER_REFS", '{"runner":{}}'),
        ("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001"),
        ("AI_WORKSHOP_GENERATION_BASE_URL", "https://example.test"),
    ],
)
def test_unsafe_provider_or_publishing_values_are_rejected(
    tmp_path: Path, key: str, value: str
) -> None:
    env = sandbox.make_environment(tmp_path, "synthetic-password", "s" * 32)
    env[key] = value
    with pytest.raises(ValueError, match="sandbox"):
        sandbox.validate_environment(env, tmp_path)


def test_runtime_ignores_hostile_dotenv_and_inherited_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from ai_workshop.config import Settings, get_settings

    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "AI_WORKSHOP_GENERATION_BASE_URL=https://example.test\nAI_WORKSHOP_GENERATION_API_KEY=synthetic-hostile\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setenv("AI_WORKSHOP_GENERATION_API_KEY", "synthetic-hostile")
    monkeypatch.setenv("AI_WORKSHOP_PROVIDER_ENDPOINT_REFS", '{"remote":"https://example.test"}')
    monkeypatch.setitem(Settings.model_config, "env_file", ".env")
    environment = sandbox.make_environment(tmp_path, "synthetic-password", "s" * 32)
    environment["AI_WORKSHOP_RAG_INDEX_CLUSTER_UUID"] = "synthetic-cluster"
    try:
        sandbox.install_environment(environment, tmp_path)
        settings = get_settings()
        assert settings.generation_base_url is None
        assert settings.generation_api_key is None
        assert settings.provider_endpoint_refs == {}
        assert settings.provider_secret_refs == {}
        assert settings.codex_runner_refs == {}
        assert settings.publishing_public_store_path == tmp_path / "public/studies.sqlite3"
        assert settings.publishing_delivery_mode == "manual"
        assert os.environ["AI_WORKSHOP_PUBLIC_API_TARGET"] == "http://127.0.0.1:18000"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("mismatch", ["document", "version", "selected_projection", "generation"])
def test_smoke_rejects_wrong_evidence_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str
) -> None:
    import copy

    import httpx

    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    smoke_spec = importlib.util.spec_from_file_location(
        "sandbox_smoke", SCRIPT.parent / "smoke_rag_sandbox.py"
    )
    assert smoke_spec and smoke_spec.loader
    smoke = importlib.util.module_from_spec(smoke_spec)
    smoke_spec.loader.exec_module(smoke)
    monkeypatch.setattr(smoke, "ROOT", tmp_path)
    state = {"workspace_id": "workspace", "document_id": "document", "asset_version_id": "version"}
    identity = {
        "document_id": "document",
        "asset_version_id": "version",
        "projection_id": "projection",
    }
    result = {
        "status": "supported",
        "answer": {"source": dict(identity)},
        "generation": {"status": "not_requested"},
        "selected_scope": {"identities": [copy.deepcopy(identity)], "fingerprint": "synthetic"},
    }
    if mismatch == "document":
        result["answer"]["source"]["document_id"] = "other"
    elif mismatch == "version":
        result["answer"]["source"]["asset_version_id"] = "other"
    elif mismatch == "selected_projection":
        result["selected_scope"]["identities"][0]["projection_id"] = "other"
    else:
        result["generation"]["status"] = "answered"
    with httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result)),
        base_url="http://sandbox",
    ) as client, pytest.raises(RuntimeError, match="sandbox_"):
        smoke.search(client, state, "configuration", "bm25")
    assert not (tmp_path / "smoke-state.json").exists()
