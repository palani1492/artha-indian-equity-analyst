from __future__ import annotations

from functools import cached_property
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Secrets are accepted only from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Sentellent Equity Research API"
    app_env: str = "production"
    log_level: str = "INFO"
    auth_mode: str = "google"
    demo_user_id: str | None = None
    cors_origins: Annotated[tuple[str, ...], NoDecode] = ("http://localhost:3000",)

    database_url: str | None = None
    db_host: str | None = None
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: str = "sentellent"
    db_username: str | None = None
    db_password: str | None = None

    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    ai_provider: str = "local"
    market_data_provider: str = "demo"
    rss_feeds: Annotated[tuple[str, ...], NoDecode] = (
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.moneycontrol.com/rss/marketreports.xml",
        "https://www.livemint.com/rss/markets",
        "https://www.business-standard.com/rss/markets-106.rss",
        "https://www.business-standard.com/rss/markets/stock-market-news-10618.rss",
        "https://www.business-standard.com/rss/markets/news-10601.rss",
        "https://www.sebi.gov.in/sebirss.xml",
    )
    rss_request_timeout_seconds: float = Field(default=10.0, ge=1, le=60)
    rss_min_request_interval_seconds: float = Field(default=1.0, ge=0.25, le=60)
    rss_max_items_per_feed: int = Field(default=100, ge=10, le=500)

    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:3000/auth/callback"
    auth_success_url: str = "http://localhost:3000"
    session_secret: str | None = Field(default=None, min_length=32)
    session_ttl_seconds: int = Field(default=86_400, ge=300, le=604_800)

    retrieval_limit: int = Field(default=6, ge=1, le=20)
    rate_limit_window_seconds: int = Field(default=60, ge=1, le=3600)
    rate_limit_chat_requests: int = Field(default=30, ge=1, le=10_000)
    rate_limit_mutation_requests: int = Field(default=20, ge=1, le=10_000)
    rate_limit_oauth_requests: int = Field(default=20, ge=1, le=10_000)

    @field_validator("app_env")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test, or production")
        return normalized

    @field_validator("auth_mode")
    @classmethod
    def validate_auth_mode(cls, value: str) -> str:
        normalized = value.lower().strip()
        if normalized not in {"demo", "google"}:
            raise ValueError("AUTH_MODE must be demo or google")
        return normalized

    @field_validator("session_secret", mode="before")
    @classmethod
    def blank_secret_is_unconfigured(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("rss_feeds", mode="before")
    @classmethod
    def parse_rss_feeds(cls, value: object) -> object:
        if isinstance(value, str) and not value.lstrip().startswith("["):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @cached_property
    def resolved_database_url(self) -> str | None:
        if self.database_url:
            return self.database_url
        if not self.db_host:
            return None
        if not self.db_username or self.db_password is None:
            raise ValueError(
                "DB_USERNAME and DB_PASSWORD are required when DB_HOST is set"
            )
        username = quote_plus(self.db_username)
        password = quote_plus(self.db_password)
        return (
            f"postgresql+asyncpg://{username}:{password}@"
            f"{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def google_oauth_configured(self) -> bool:
        return bool(
            self.google_client_id and self.google_client_secret and self.session_secret
        )


def get_settings() -> Settings:
    return Settings()
