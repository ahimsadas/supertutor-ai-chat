from functools import lru_cache
from typing import Optional
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Compute absolute backend directory and env file path regardless of CWD
# For this file at backend/app/core/config.py:
#   Path(__file__).resolve().parents[2] -> <repo_root>/backend
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Required at runtime only when corresponding components are used.
    """

    # General
    APP_ENV: str = "dev"

    # Supabase
    SUPABASE_URL: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    SUPABASE_DB_URL: Optional[str] = None  # optional: direct DB access later

    # Provider API Keys (optional for now; used when a provider is selected)
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    XAI_API_KEY: Optional[str] = None

    # Pydantic settings configuration
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Expose the absolute env file path for debugging endpoints
    ENV_FILE_PATH: str = str(ENV_FILE)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (reads env file once per process)."""
    return Settings()
