from functools import lru_cache
from ipaddress import IPv6Address
from pathlib import Path
from re import fullmatch
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from ai_workshop.labs.rag.generation.codex_runner_registry import (
    CodexRunnerSettings,
    is_safe_codex_runner_reference,
)
from ai_workshop.platform.publishing.package import PublicPersona


class LearningLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    title_max_chars: int = Field(default=200, gt=0)
    body_max_chars: int = Field(default=100_000, gt=0)
    max_references: int = Field(default=20, gt=0)
    max_text_field_chars: int = Field(default=20_000, gt=0)
    max_collection_items: int = Field(default=100, gt=0)
    page_default: int = Field(default=20, gt=0)
    page_max: int = Field(default=100, gt=0)
    cursor_max_chars: int = Field(default=4096, gt=0)
    aggregate_draft_max_bytes: int = Field(default=262_144, gt=0)

    @model_validator(mode="after")
    def require_page_default_within_maximum(self) -> Self:
        if self.page_default > self.page_max:
            raise ValueError("The learning page default must not exceed its maximum.")
        return self


class PublishingLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    title_max_chars: int = Field(default=200, gt=0)
    text_field_max_chars: int = Field(default=100_000, gt=0)
    max_collection_items: int = Field(default=100, gt=0)
    aggregate_content_max_bytes: int = Field(default=262_144, gt=0)
    request_id_max_chars: int = Field(default=200, gt=0, le=200)
    page_default: int = Field(default=20, gt=0)
    page_max: int = Field(default=100, gt=0)

    @model_validator(mode="after")
    def require_page_default_within_maximum(self) -> Self:
        if self.page_default > self.page_max:
            raise ValueError("The publishing page default must not exceed its maximum.")
        return self


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
    library_page_size: int = Field(default=50, strict=True, ge=1, le=200)
    library_max_page_size: int = Field(default=200, strict=True, ge=1, le=200)
    library_max_depth: int = Field(default=64, strict=True, ge=1, le=256)
    library_cursor_max_chars: int = Field(default=4096, strict=True, ge=1, le=4096)
    original_max_bytes: int = Field(default=50 * 1024 * 1024, strict=True, gt=0)
    text_preview_max_bytes: int = Field(default=2 * 1024 * 1024, strict=True, gt=0)
    pdf_max_pages: int = Field(default=1000, strict=True, gt=0)
    pdf_max_pixels: int = Field(default=16_000_000, strict=True, gt=0)
    pdf_timeout_seconds: int = Field(default=15, strict=True, gt=0)
    pdf_max_concurrent: int = Field(default=2, strict=True, gt=0)
    elasticsearch_url: str = "http://127.0.0.1:9200"
    elasticsearch_index_prefix: str = "ai-workshop-rag"
    model_cache_root: Path = Path(".local-data/models")
    evaluation_authoring_max_documents: int = Field(default=20, strict=True, ge=1, le=100)
    evaluation_authoring_max_evidence_units: int = Field(default=1000, strict=True, ge=1, le=10_000)
    evaluation_authoring_max_response_bytes: int = Field(
        default=2_097_152, strict=True, ge=1, le=16_777_216
    )
    evaluation_authoring_max_cases: int = Field(default=50, strict=True, ge=1, le=500)
    rag_selected_documents_max_count: int = Field(default=100, strict=True, ge=1, le=1000)

    @field_validator(
        "evaluation_authoring_max_documents",
        "evaluation_authoring_max_evidence_units",
        "evaluation_authoring_max_response_bytes",
        "evaluation_authoring_max_cases",
        "rag_selected_documents_max_count",
        mode="before",
    )
    @classmethod
    def parse_integer_environment_limits(cls, value: object) -> object:
        if isinstance(value, str) and fullmatch(r"[0-9]{1,8}", value):
            return int(value)
        return value

    provider_endpoint_refs: dict[str, str] = Field(default_factory=dict)
    provider_secret_refs: dict[str, SecretStr] = Field(default_factory=dict)
    codex_runner_refs: dict[str, CodexRunnerSettings] = Field(default_factory=dict, repr=False)
    codex_allowed_admin_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    generation_base_url: str | None = None
    generation_api_key: SecretStr | None = None
    setup_company_workspace_name: str = "전사 자산운용 지식"
    setup_personal_workspace_name: str = "개인 연구"
    learning_limits: LearningLimits = Field(default_factory=LearningLimits)
    publishing_public_store_path: Path = Path(".local-data/public/studies.sqlite3")
    publishing_delivery_mode: Literal["local", "manual"] = "local"
    publishing_allowed_admin_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    )
    publishing_approved_public_personas: tuple[PublicPersona, ...] = ()
    publishing_limits: PublishingLimits = Field(default_factory=PublishingLimits)

    @model_validator(mode="after")
    def require_library_default_within_maximum(self) -> Self:
        if self.library_page_size > self.library_max_page_size:
            raise ValueError("The library page default must not exceed its maximum.")
        return self

    @model_validator(mode="after")
    def require_text_preview_within_original_limit(self) -> Self:
        if self.text_preview_max_bytes > self.original_max_bytes:
            raise ValueError("The text preview limit must not exceed the original limit.")
        return self

    @field_validator("codex_allowed_admin_origins")
    @classmethod
    def validate_codex_admin_origins(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) > 32 or len(set(values)) != len(values):
            raise ValueError("Codex admin origins must be non-empty, bounded and unique.")
        for value in values:
            parsed = urlsplit(value)
            if (
                len(value) > 2048
                or value != value.strip()
                or not value.isascii()
                or not value.isprintable()
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or "*" in value
                or "\\" in value
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
                or value != f"{parsed.scheme}://{parsed.netloc}"
                or parsed.netloc.endswith(":")
            ):
                raise ValueError("Codex admin origins must be exact HTTP origins.")
            if ":" in parsed.hostname:
                IPv6Address(parsed.hostname)
            elif any(
                fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) is None
                for label in parsed.hostname.split(".")
            ):
                raise ValueError("Codex admin origins require a valid host.")
            # URL splitting defers numeric/range port validation until this property is read.
            if parsed.port is not None and parsed.port < 1:
                raise ValueError("Codex admin origins require valid ports.")
        return values

    @field_validator("publishing_allowed_admin_origins")
    @classmethod
    def validate_publishing_admin_origins(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("Publishing admin origins must be non-empty and unique.")
        for value in values:
            parsed = urlsplit(value)
            if (
                value == "null"
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Publishing admin origins must be exact HTTP origins.")
        return values

    @model_validator(mode="after")
    def reject_local_publication_delivery_in_production(self) -> Self:
        if self.environment == "production" and self.publishing_delivery_mode == "local":
            raise ValueError("Production publishing requires manual delivery mode.")
        return self

    @field_validator("codex_runner_refs", mode="before")
    @classmethod
    def validate_codex_runner_refs(cls, value: object) -> object:
        if not isinstance(value, dict) or any(
            not is_safe_codex_runner_reference(key) for key in value
        ):
            raise ValueError("Codex runner references require a map with valid reference names.")
        return value

    @field_validator("provider_endpoint_refs", mode="before")
    @classmethod
    def validate_provider_endpoint_refs(cls, value: object) -> object:
        entries = _validate_provider_reference_map(value)
        cleaned: dict[str, str] = {}
        for key, item in entries.items():
            if not isinstance(item, str) or not item.strip():
                raise ValueError("Provider endpoint references require non-empty string values.")
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
                raise ValueError("Provider secret references require non-empty string values.")
            if not configured_value.strip():
                raise ValueError("Provider secret references require non-empty string values.")
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
    if any(not isinstance(key, str) or not _is_safe_provider_reference_name(key) for key in value):
        raise ValueError("Provider references contain an invalid reference name.")
    return value


def _is_safe_provider_reference_name(value: str) -> bool:
    return (
        fullmatch(r"[a-z][a-z0-9]*-[a-z0-9]+(?:-[a-z0-9]+)*", value) is not None
        and not value.startswith(("sk-", "sess-", "key-", "token-", "secret-"))
        and fullmatch(r"[0-9a-f]{24,}", value) is None
    )
