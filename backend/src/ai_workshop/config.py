from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AI_WORKSHOP_",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    secret_key: SecretStr = Field(min_length=32)
    database_url: str = "postgresql+psycopg://ai_workshop:ai_workshop@127.0.0.1:5432/ai_workshop"
    redis_url: str = "redis://127.0.0.1:6379/0"
    object_store_root: Path = Path(".local-data/objects")

    @property
    def secure_cookies(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # Loaded by BaseSettings environment sources.
