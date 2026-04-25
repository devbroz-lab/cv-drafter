"""Application settings loaded from environment (see `.env.example`)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "cv-uploads"
    api_secret_key: str = ""
    debug: bool = False

    # Anthropic — required for the 6-agent CV pipeline
    anthropic_api_key: str = ""

    # Comma-separated list of allowed CORS origins.
    # Default "*" for local dev — lock this down before going to production.
    # Example: "https://app.example.com,https://staging.example.com"
    cors_origins: str = "*"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS_ORIGINS env var into a list FastAPI can consume."""
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
