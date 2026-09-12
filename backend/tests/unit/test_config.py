import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_workshop.config import Settings


@pytest.mark.parametrize(
    "field",
    [
        "evaluation_authoring_max_documents",
        "evaluation_authoring_max_evidence_units",
        "evaluation_authoring_max_response_bytes",
        "evaluation_authoring_max_cases",
        "rag_selected_documents_max_count",
    ],
)
@pytest.mark.parametrize("invalid", [0, -1, True, 10**10])
def test_configured_integer_limits_are_positive_bounded_integers(field, invalid):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None, secret_key="synthetic-authoring-test-key-32-chars", **{field: invalid}
        )


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "https://example.invalid/path",
        "https://user@example.invalid",
        "https://example.invalid?query=1",
        "https://example.invalid#fragment",
        "https://example.invalid:bad",
        "https://example.invalid:99999",
        " https://example.invalid",
        "https://example.invalid\n",
        "https://*",
        "ftp://example.invalid",
        "http://",
        "https://exa mple.invalid",
        "https://example.invalid?",
        "https://example.invalid#",
        "https://example.invalid:",
        "https://bad..invalid",
    ],
)
def test_codex_origins_are_exact_strict_http_origins(origin):
    with pytest.raises(ValidationError):
        Settings(secret_key="x" * 32, codex_allowed_admin_origins=(origin,), _env_file=None)


def test_codex_origins_use_separate_typed_setting_and_local_defaults():
    settings = Settings(secret_key="x" * 32, _env_file=None)
    assert settings.codex_allowed_admin_origins == (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    changed = Settings(
        secret_key="x" * 32, codex_allowed_admin_origins=("https://codex.example",), _env_file=None
    )
    assert changed.publishing_allowed_admin_origins == settings.publishing_allowed_admin_origins


def test_settings_read_prefixed_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_WORKSHOP_ENVIRONMENT", "test")
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "x" * 32)
    monkeypatch.setenv(
        "AI_WORKSHOP_DATABASE_URL",
        "postgresql+psycopg://test:test@localhost:5432/test",
    )

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.secret_key.get_secret_value() == "x" * 32
    assert settings.object_store_root == Path(".local-data/objects")


def test_settings_reject_short_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_WORKSHOP_SECRET_KEY", "too-short")

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    error = exc_info.value.errors()[0]
    assert error["loc"] == ("secret_key",)
    assert error["type"] == "too_short"


def test_rag_runtime_settings_have_local_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "AI_WORKSHOP_ELASTICSEARCH_URL",
        "AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX",
        "AI_WORKSHOP_MODEL_CACHE_ROOT",
    ):
        monkeypatch.delenv(variable, raising=False)

    settings = Settings(secret_key="x" * 32, _env_file=None)

    assert settings.elasticsearch_url == "http://127.0.0.1:9200"
    assert settings.elasticsearch_index_prefix == "ai-workshop-rag"
    assert settings.model_cache_root.name == "models"


def test_codex_runner_refs_default_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AI_WORKSHOP_CODEX_RUNNER_REFS", raising=False)
    settings = Settings(secret_key="x" * 32, _env_file=None)
    assert settings.codex_runner_refs == {}


def test_codex_runner_refs_parse_environment_without_filesystem_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = {
        "executable": str(tmp_path / "uninstalled" / "synthetic.exe"),
        "request_root": str(tmp_path / "uncreated"),
        "expected_cli_version": "1.2.3",
        "executable_sha256": "a" * 64,
        "environment": {"temp": str(tmp_path / "unused-temp")},
    }
    monkeypatch.setenv("AI_WORKSHOP_CODEX_RUNNER_REFS", json.dumps({"codex-test-v1": runner}))
    settings = Settings(secret_key="x" * 32, _env_file=None)
    entry = settings.codex_runner_refs["codex-test-v1"]
    assert entry.environment == {"TEMP": runner["environment"]["temp"]}
    assert entry.executable == Path(runner["executable"])
    assert not entry.request_root.exists()
    assert str(tmp_path) not in repr(settings)


@pytest.mark.parametrize("reference", ["bad", "sk-test", "A-test", "a-" + "x" * 119])
def test_codex_runner_reference_keys_reject_safely(reference: str) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(secret_key="x" * 32, codex_runner_refs={reference: {}}, _env_file=None)
    assert reference not in str(error.value)


def test_codex_settings_preserve_existing_http_provider_settings() -> None:
    settings = Settings(
        secret_key="x" * 32,
        _env_file=None,
        provider_endpoint_refs={"http-local": " http://127.0.0.1:8001 "},
        provider_secret_refs={"http-secret": "synthetic-http-secret"},
        generation_base_url="http://127.0.0.1:8002",
        generation_api_key="synthetic-key",
    )
    assert settings.provider_endpoint_refs == {"http-local": "http://127.0.0.1:8001"}
    assert (
        settings.provider_secret_refs["http-secret"].get_secret_value() == "synthetic-http-secret"
    )
    assert settings.generation_base_url == "http://127.0.0.1:8002"
    assert settings.generation_api_key.get_secret_value() == "synthetic-key"


def test_authoring_integer_limits_can_be_configured_by_environment(monkeypatch):
    monkeypatch.setenv("AI_WORKSHOP_EVALUATION_AUTHORING_MAX_DOCUMENTS", "12")
    settings = Settings(secret_key="synthetic-test-secret-at-least-32-chars", _env_file=None)
    assert settings.evaluation_authoring_max_documents == 12


def test_selected_document_limit_can_be_configured_by_decimal_environment_value(monkeypatch):
    monkeypatch.setenv("AI_WORKSHOP_RAG_SELECTED_DOCUMENTS_MAX_COUNT", "17")

    settings = Settings(secret_key="synthetic-test-secret-at-least-32-chars", _env_file=None)

    assert settings.rag_selected_documents_max_count == 17


@pytest.mark.parametrize("value", ["17.0", "+17", " 17", "17 ", "seventeen"])
def test_selected_document_limit_rejects_non_decimal_environment_values(monkeypatch, value):
    monkeypatch.setenv("AI_WORKSHOP_RAG_SELECTED_DOCUMENTS_MAX_COUNT", value)

    with pytest.raises(ValidationError):
        Settings(secret_key="synthetic-test-secret-at-least-32-chars", _env_file=None)


@pytest.mark.parametrize("value", ["0", "1001"])
def test_selected_document_limit_rejects_out_of_range_environment_values(monkeypatch, value):
    monkeypatch.setenv("AI_WORKSHOP_RAG_SELECTED_DOCUMENTS_MAX_COUNT", value)

    with pytest.raises(ValidationError):
        Settings(secret_key="synthetic-test-secret-at-least-32-chars", _env_file=None)
