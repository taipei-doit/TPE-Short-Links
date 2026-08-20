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

    # --- PIN-protected file sharing (/f/{code}) ---
    # Object storage bucket. Empty means "store on local disk", which is what
    # tests and local development use.
    FILE_STORAGE_BUCKET: str = ""
    FILE_STORAGE_LOCAL_DIR: str = ""
    FILE_STORAGE_PREFIX: str = "shared-files"
    # Cloud Run rejects request bodies over 32 MiB, so the ceiling has to stay
    # under that once multipart overhead is counted.
    MAX_UPLOAD_MB: int = 25
    FILE_CODE_LENGTH: int = 6
    # Signs the short-lived download tokens issued after a correct PIN. Falls
    # back to a value derived from INTERNAL_API_TOKEN so a deployment that
    # already has that secret needs no extra configuration.
    FILE_DOWNLOAD_SECRET: str = ""
    FILE_DOWNLOAD_TOKEN_TTL_SECONDS: int = 300
    # Wrong-PIN attempts tolerated before a share link locks, and for how long.
    FILE_PIN_MAX_ATTEMPTS: int = 5
    FILE_PIN_LOCKOUT_MINUTES: int = 15

    def reserved_codes_set(self) -> set[str]:
        raw = (self.RESERVED_CODES or "").strip()
        if not raw:
            return set()
        return {c.strip() for c in raw.split(",") if c.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()

