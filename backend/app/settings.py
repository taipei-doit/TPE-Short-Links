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
    # Where the static admin/public frontend is hosted. /qr/{code} on this
    # service 302s there so agencies get a memorable url.taipei address for
    # the QR style studio.
    FRONTEND_BASE_URL: str = "https://url-taipei.web.app"
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
    # Ceiling for bytes PROXIED THROUGH this service. Cloud Run rejects request
    # bodies over 32 MiB at the edge, before we see them. Measured against the
    # deployed service: a 28 MB upload reaches the app, 32 MB comes back as a
    # 413 from the infrastructure. 30 leaves room for the multipart framing.
    MAX_UPLOAD_MB: int = 30
    # Ceiling for a single file overall. Anything above MAX_UPLOAD_MB has to go
    # straight from the browser to object storage, which has no such limit.
    MAX_FILE_MB: int = 2048
    # How long a browser has to finish an upload before its session token dies.
    UPLOAD_SESSION_TTL_SECONDS: int = 6 * 60 * 60
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
        codes = {c.strip() for c in raw.split(",") if c.strip()} if raw else set()
        # /qr/*, /check/* and /assets/* are claimed by app routes, so short
        # links with these codes could never be reached. Case variants of
        # "qr" are technically reachable (routing is case-sensitive) but
        # reserved anyway to avoid confusion.
        codes |= {"qr", "QR", "Qr", "qR", "assets", "check"}
        return codes


@lru_cache
def get_settings() -> Settings:
    return Settings()

