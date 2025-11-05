from functools import lru_cache
from typing import Optional, Dict, Any
from pathlib import Path

from pydantic import field_validator
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
    SUPABASE_FILES_BUCKET: str = "files"

    # Backend base URL (for CLI clients)
    BACKEND_BASE_URL: str = "http://localhost:8000"

    # Provider API Keys (optional for now; used when a provider is selected)
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    XAI_API_KEY: Optional[str] = None
    # OpenRouter (OpenAI-compatible proxy)
    OPENROUTER_API_KEY: Optional[str] = None
    OPENROUTER_SITE_URL: Optional[str] = None   # HTTP-Referer
    OPENROUTER_APP_TITLE: Optional[str] = None  # X-Title

    # Chunking (optional overrides)
    CHUNK_SIZE_CHARS: int = 500
    CHUNK_OVERLAP_CHARS: int = 60

    # Upload/ingestion caps
    # None => router/HTTP upload has no preflight byte cap
    FILES_UPLOAD_MAX_MB: Optional[float] = None
    # Runner/ingestion cap used to mark files.ingestion_failed='size_cap'
    FILES_INGEST_MAX_MB: float = 50.0

    # Embeddings
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_BATCH_SIZE: int = 64
    EMBEDDING_DIM: int = 1536

    # Pydantic settings configuration
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Expose the absolute env file path for debugging endpoints
    ENV_FILE_PATH: str = str(ENV_FILE)

    # Validators
    @field_validator("FILES_UPLOAD_MAX_MB", mode="before")
    @classmethod
    def _coerce_upload_mb(cls, v):  # type: ignore[no-untyped-def]
        if v is None:
            return None
        s = str(v).strip()
        if s == "":
            return None
        try:
            x = float(s)
        except Exception:
            return None
        if x <= 0:
            return None
        return x

    @field_validator("BACKEND_BASE_URL", mode="before")
    @classmethod
    def _normalize_base_url(cls, v):  # type: ignore[no-untyped-def]
        s = (str(v) if v is not None else "http://localhost:8000").strip()
        return s or "http://localhost:8000"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance (reads env file once per process)."""
    return Settings()


def settings_log_summary(include: Optional[list[str]] = None) -> Dict[str, Any]:
    """Return a dict of safe, non-secret settings suitable for INFO logs.

    Secrets (anything ending with _KEY) are excluded regardless of include.
    """
    s = get_settings()
    allow: Dict[str, Any] = {
        "APP_ENV": s.APP_ENV,
        "BACKEND_BASE_URL": s.BACKEND_BASE_URL,
        "SUPABASE_FILES_BUCKET": s.SUPABASE_FILES_BUCKET,
        "CHUNK_SIZE_CHARS": s.CHUNK_SIZE_CHARS,
        "CHUNK_OVERLAP_CHARS": s.CHUNK_OVERLAP_CHARS,
        "FILES_UPLOAD_MAX_MB": s.FILES_UPLOAD_MAX_MB,
        "FILES_INGEST_MAX_MB": s.FILES_INGEST_MAX_MB,
        "EMBEDDING_MODEL": s.EMBEDDING_MODEL,
        "EMBEDDING_BATCH_SIZE": s.EMBEDDING_BATCH_SIZE,
        "EMBEDDING_DIM": s.EMBEDDING_DIM,
    }
    if include:
        out = {}
        for k in include:
            if k.endswith("_KEY"):
                continue
            if k in allow:
                out[k] = allow[k]
        return out
    return allow
