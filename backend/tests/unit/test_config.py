from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_workshop.config import Settings


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


def test_rag_runtime_settings_have_local_defaults() -> None:
    settings = Settings(secret_key="x" * 32)

    assert settings.elasticsearch_url == "http://127.0.0.1:9200"
    assert settings.elasticsearch_index_prefix == "ai-workshop-rag"
    assert settings.model_cache_root.name == "models"
