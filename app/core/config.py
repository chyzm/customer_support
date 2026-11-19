from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and `.env`.

    Pydantic validates types at startup, so a bad config fails immediately
    instead of on the first request.
    """

    jev_mode: Literal["mock", "live"] = "mock"

    # SecretStr masks the value in repr() and logs. Call .get_secret_value()
    # only at the moment you build the HTTP header.
    typesafe_api_key: SecretStr | None = None

    # Pinned version. "jev-latest" is an alias that moves, so thresholds you
    # tune today could silently change behaviour later.
    jev_model: str = "jev-1.14.0"
    jev_api_url: str = "https://api.typesafe.ai/v1/systemone"
    jev_timeout_seconds: float = 15.0

    database_url: str = "sqlite:///./triage.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def _live_mode_requires_key(self) -> "Settings":
        if self.jev_mode == "live" and not (
            self.typesafe_api_key and self.typesafe_api_key.get_secret_value()
        ):
            raise ValueError("TYPESAFE_API_KEY is required when JEV_MODE=live")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
