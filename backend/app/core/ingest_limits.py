import logging

from app.core.config import get_settings

log = logging.getLogger(__name__)


def ingest_cap_bytes() -> int:
    """Backward-compatible accessor for the ingestion cap in bytes.

    Reads FILES_INGEST_MAX_MB from centralized settings (backend/.env auto-loaded).
    Defaults to 50 MB when unset or invalid.
    """
    try:
        s = get_settings()
        mb = float(getattr(s, "FILES_INGEST_MAX_MB", 50.0) or 50.0)
    except Exception:
        mb = 50.0
    if mb <= 0:
        mb = 50.0
    cap = int(mb * 1024 * 1024)
    log.info("INGEST_CAP mb=%.6f cap_bytes=%d", mb, cap)
    return cap
