from __future__ import annotations

from typing import Optional

from .supabase import SupabaseStorage
from .base import StorageBackend

_singleton: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """Return the Supabase storage backend singleton."""
    global _singleton
    if _singleton is None:
        _singleton = SupabaseStorage()
    return _singleton
