from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and `.env`.

    Pydantic validates operational limits at startup. Bad configuration fails
    before the API accepts traffic instead of during a customer request.
    """

    jev_mode: Literal["mock", "live"] = "mock"

    # Outbound provider credential. This is separate from inbound client keys.
    typesafe_api_key: SecretStr | None = None
    jev_model: str = "jev-1.14.0"
    jev_api_url: str = "https://api.typesafe.ai/v1/systemone"
    jev_timeout_seconds: float = Field(15.0, gt=0, le=120)

    # Total outbound attempts, including the first call. Keeping this name
    # explicit avoids the common ambiguity where "3 retries" means 4 calls.
    jev_max_attempts: int = Field(3, ge=1, le=5)
    jev_retry_base_seconds: float = Field(0.25, ge=0, le=10)
    jev_retry_max_seconds: float = Field(2.0, ge=0, le=30)

    # Inbound authentication. Entries use "client-id:secret" and are kept in a
    # SecretStr so settings repr/logs cannot reveal the whole key list.
    api_auth_enabled: bool = False
    client_api_keys: SecretStr | None = None

    # Process-local sliding-window quota. It resets on restart and is not shared
    # across multiple Uvicorn workers; use a shared store before scaling out.
    rate_limit_requests: int = Field(60, ge=1, le=100_000)
    rate_limit_window_seconds: int = Field(60, ge=1, le=3_600)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "sqlite:///./triage.db"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def parsed_client_api_keys(self) -> dict[str, str]:
        """Parse `client-id:secret` pairs without exposing them in validation errors."""
        if self.client_api_keys is None:
            return {}

        result: dict[str, str] = {}
        raw = self.client_api_keys.get_secret_value()
        for item in raw.split(","):
            item = item.strip()
            if not item:
                continue
            if ":" not in item:
                raise ValueError("CLIENT_API_KEYS entries must use client-id:secret")
            client_id, secret = (part.strip() for part in item.split(":", 1))
            if not client_id or not secret:
                raise ValueError("CLIENT_API_KEYS entries require a non-empty client ID and secret")
            if client_id in result:
                raise ValueError("CLIENT_API_KEYS contains a duplicate client ID")
            if secret in result.values():
                raise ValueError("CLIENT_API_KEYS contains a duplicate client secret")
            result[client_id] = secret
        return result

    @model_validator(mode="after")
    def _validate_operational_configuration(self) -> "Settings":
        if self.jev_retry_max_seconds < self.jev_retry_base_seconds:
            raise ValueError("JEV_RETRY_MAX_SECONDS must be >= JEV_RETRY_BASE_SECONDS")

        provider_key_present = bool(
            self.typesafe_api_key and self.typesafe_api_key.get_secret_value()
        )
        if self.jev_mode == "live" and not provider_key_present:
            raise ValueError("TYPESAFE_API_KEY is required when JEV_MODE=live")

        parsed_keys = self.parsed_client_api_keys()
        if self.api_auth_enabled and not parsed_keys:
            raise ValueError("CLIENT_API_KEYS is required when API_AUTH_ENABLED=true")
        # Live mode sends real customer text to a paid provider. Do not allow it
        # to start as an unauthenticated public API by mistake.
        if self.jev_mode == "live" and not self.api_auth_enabled:
            raise ValueError("API_AUTH_ENABLED must be true when JEV_MODE=live")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
