from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Default supports "local-first" dev (docker compose Postgres).
    DATABASE_URL: str = "postgresql+psycopg://tpe:tpe@localhost:5432/tpe_short_links"
    ALLOW_HTTP_URLS: bool = False
    SHORTLINK_CODE_LENGTH: int = 4
    RESERVED_CODES: str = ""
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    # Firebase:
    # - FIREBASE_PROJECT_ID is used to verify Firebase ID tokens (token `aud` claim).
    # - FIREBASE_APP_ID is the Web app's App ID (used by the frontend Firebase config); it is not used
    #   for backend ID token verification.
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_APP_ID: str = ""
    # Shared secret used by the magic-link Cloud Function to ask this service
    # whether an email is whitelisted. Empty disables the internal endpoint.
    INTERNAL_API_TOKEN: str = ""

    def reserved_codes_set(self) -> set[str]:
        raw = (self.RESERVED_CODES or "").strip()
        if not raw:
            return set()
        return {c.strip() for c in raw.split(",") if c.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()

