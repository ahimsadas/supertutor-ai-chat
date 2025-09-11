from __future__ import annotations

from typing import Optional
from functools import lru_cache

from ..core.config import get_settings


@lru_cache(maxsize=1)
def _create_client():
    """Create and cache a Supabase client using env-driven settings.

    Raises:
        RuntimeError: if required env vars are missing.
    """
    settings = get_settings()

    url: Optional[str] = settings.SUPABASE_URL
    key: Optional[str] = settings.SUPABASE_SERVICE_ROLE_KEY

    if not url:
        raise RuntimeError("Missing required env var: SUPABASE_URL")
    if not key:
        raise RuntimeError(
            "Missing required env var: SUPABASE_SERVICE_ROLE_KEY (server-only key)"
        )

    # Import lazily to avoid import-time errors when unused.
    from supabase import create_client  # type: ignore

    return create_client(url, key)


def get_supabase_client():
    """Return a lazy, singleton Supabase client instance.

    This does not make any network calls on import. The client is created on first use.
    """
    return _create_client()
