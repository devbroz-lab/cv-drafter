"""Application settings loaded from environment (see `.env.example`)."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always load the cv-drafter/.env next to this package, not cwd-relative ".env"
# (uvicorn is often started from a parent folder, which broke GOOGLE_CLIENT_ID).
_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_ENV_FILE = _PACKAGE_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "cv-uploads"
    api_secret_key: str = ""
    jwt_secret: str = ""
    jwt_refresh_secret: str = ""
    access_token_expires_minutes: int = 15
    refresh_token_expires_days: int = 7
    google_client_id: str = ""
    microsoft_client_id: str = ""
    # Comma-separated emails allowed to register/login. Empty = built-in beta list.
    auth_email_allowlist: str = ""
    debug: bool = False

    # Anthropic — required for the 6-agent CV pipeline
    anthropic_api_key: str = ""

    # Comma-separated list of allowed CORS origins.
    # Default "*" for local dev — lock this down before going to production.
    # Example: "https://app.example.com,https://staging.example.com"
    cors_origins: str = "*"

    # Metering — USD rates converted to credits via credit_usd_value (1 credit = $1 by default).
    meter_credit_usd: float = 1.0
    meter_pipeline_run_usd: float = 2.0
    meter_revision_usd: float = 0.20
    meter_initial_grant_credits: float = 20.0

    @field_validator("google_client_id", "microsoft_client_id", mode="before")
    @classmethod
    def _strip_oauth_client_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS env var into a list FastAPI can consume."""
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
