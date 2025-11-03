import os
import logging

log = logging.getLogger(__name__)


def ingest_cap_bytes() -> int:
    raw = os.getenv("FILES_INGEST_MAX_MB", "50")
    try:
        mb = float(raw)
    except ValueError:
        log.warning("FILES_INGEST_MAX_MB invalid=%r, defaulting to 50MB", raw)
        mb = 50.0
    if mb <= 0:
        log.warning("FILES_INGEST_MAX_MB <= 0 (%r), defaulting to 50MB", raw)
        mb = 50.0
    cap = int(mb * 1024 * 1024)
    log.info("INGEST_CAP raw=%r parsed_mb=%.6f cap_bytes=%d", raw, mb, cap)
    return cap
