from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_workshop.config import Settings
from ai_workshop.platform.publishing.package import PublicPersona
from ai_workshop.platform.publishing.settings import PublicSettings


def test_private_publishing_settings_have_explicit_safe_local_defaults() -> None:
    settings = Settings(secret_key="x" * 32, _env_file=None)

    assert settings.publishing_public_store_path == Path(
        ".local-data/public/studies.sqlite3"
    )
    assert settings.publishing_delivery_mode == "local"
    assert settings.publishing_allowed_admin_origins == (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    assert settings.publishing_approved_public_personas == ()


def test_private_publishing_settings_parse_typed_registry_and_manual_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_WORKSHOP_PUBLISHING_DELIVERY_MODE", "manual")
    monkeypatch.setenv(
        "AI_WORKSHOP_PUBLISHING_ALLOWED_ADMIN_ORIGINS",
        '["https://admin.example.test"]',
    )
    monkeypatch.setenv(
        "AI_WORKSHOP_PUBLISHING_APPROVED_PUBLIC_PERSONAS",
        '[{"slug":"reviewer","label":"Approved reviewer"}]',
    )

    settings = Settings(secret_key="x" * 32, _env_file=None)

    assert settings.publishing_delivery_mode == "manual"
    assert settings.publishing_allowed_admin_origins == (
        "https://admin.example.test",
    )
    assert settings.publishing_approved_public_personas == (
        PublicPersona(slug="reviewer", label="Approved reviewer"),
    )


def test_production_rejects_same_process_local_delivery() -> None:
    with pytest.raises(ValidationError) as failure:
        Settings(secret_key="x" * 32, environment="production", _env_file=None)

    assert failure.value.errors()[0]["type"] == "value_error"


def test_public_settings_need_only_the_public_prefix(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store = tmp_path / "public.sqlite3"
    monkeypatch.setenv("AI_WORKSHOP_PUBLIC_STORE_PATH", str(store))
    monkeypatch.delenv("AI_WORKSHOP_SECRET_KEY", raising=False)
    monkeypatch.delenv("AI_WORKSHOP_DATABASE_URL", raising=False)

    settings = PublicSettings()

    assert settings.store_path == store
    assert set(PublicSettings.model_fields) == {"store_path"}


def test_request_id_limit_cannot_exceed_postgresql_column_capacity() -> None:
    with pytest.raises(ValidationError) as failure:
        Settings(
            secret_key="x" * 32,
            publishing_limits={"request_id_max_chars": 201},
            _env_file=None,
        )

    assert failure.value.errors()[0]["type"] == "less_than_equal"
