from functools import lru_cache
from pathlib import Path
from re import fullmatch
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AI_WORKSHOP_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    environment: Literal["local", "test", "production"] = "local"
    secret_key: SecretStr = Field(min_length=32)
    database_url: str = "postgresql+psycopg://ai_workshop:ai_workshop@127.0.0.1:5432/ai_workshop"
    redis_url: str = "redis://127.0.0.1:6379/0"
    object_store_root: Path = Path(".local-data/objects")
    elasticsearch_url: str = "http://127.0.0.1:9200"
    elasticsearch_index_prefix: str = "ai-workshop-rag"
    model_cache_root: Path = Path(".local-data/models")
    provider_endpoint_refs: dict[str, str] = Field(default_factory=dict)
    provider_secret_refs: dict[str, SecretStr] = Field(default_factory=dict)
    generation_base_url: str | None = None
    generation_api_key: SecretStr | None = None
    setup_company_workspace_name: str = "전사 자산운용 지식"
    setup_personal_workspace_name: str = "개인 연구"

    @field_validator("provider_endpoint_refs", mode="before")
    @classmethod
    def validate_provider_endpoint_refs(cls, value: object) -> object:
        entries = _validate_provider_reference_map(value)
        cleaned: dict[str, str] = {}
        for key, item in entries.items():
            if not isinstance(item, str) or not item.strip():
                raise ValueError(
                    "Provider endpoint references require non-empty string values."
                )
            cleaned[key] = item.strip()
        return cleaned

    @field_validator("provider_secret_refs", mode="before")
    @classmethod
    def validate_provider_secret_refs(cls, value: object) -> object:
        entries = _validate_provider_reference_map(value)
        for item in entries.values():
            if isinstance(item, SecretStr):
                configured_value = item.get_secret_value()
            elif isinstance(item, str):
                configured_value = item
            else:
                raise ValueError(
                    "Provider secret references require non-empty string values."
                )
            if not configured_value.strip():
                raise ValueError(
                    "Provider secret references require non-empty string values."
                )
        return entries

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # Loaded by BaseSettings environment sources.


def _validate_provider_reference_map(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Provider references must be a JSON object.")
    if any(
        not isinstance(key, str) or not _is_safe_provider_reference_name(key)
        for key in value
    ):
        raise ValueError("Provider references contain an invalid reference name.")
    return value


def _is_safe_provider_reference_name(value: str) -> bool:
    return (
        fullmatch(r"[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*", value)
        is not None
        and not value.startswith(("sk-", "sess-", "key-", "token-", "secret-"))
        and fullmatch(r"[0-9a-f]{24,}", value) is None
    )
