from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PublicSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        env_prefix="AI_WORKSHOP_PUBLIC_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    store_path: Path = Field()
