from __future__ import annotations

import time
from logging import getLogger
from typing import List

from app.core.config import get_settings

logger = getLogger("supertutor.embedder")

_MODEL = "text-embedding-3-small"
_DIM = 1536


def embed_snippets(snippets: List[str], *, batch_size: int = 64) -> List[List[float]]:
    settings = get_settings()
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise RuntimeError("Missing required env var: OPENAI_API_KEY")

    if not isinstance(snippets, list):
        raise TypeError("snippets must be a list of strings")

    n = len(snippets)
    if n == 0:
        return []

    try:
        from openai import OpenAI  # type: ignore
    except Exception as e:
        raise RuntimeError(f"Failed to import OpenAI client: {e}") from e

    client = OpenAI(api_key=api_key)

    out: List[List[float]] = []
    t0 = time.perf_counter()
    bs = max(1, int(batch_size))
    for i in range(0, n, bs):
        batch = [str(x or " ") for x in snippets[i : i + bs]]
        bt0 = time.perf_counter()
        resp = client.embeddings.create(model=_MODEL, input=batch)
        data = list(getattr(resp, "data", []) or [])
        data_sorted = sorted(data, key=lambda d: getattr(d, "index", 0))
        vecs = [list(getattr(d, "embedding", []) or []) for d in data_sorted]
        out.extend(vecs)
        bt1 = time.perf_counter()
        logger.debug("embedder.batch model=%s n=%d secs=%.3f", _MODEL, len(batch), (bt1 - bt0))

    t1 = time.perf_counter()

    if len(out) != n:
        raise RuntimeError(f"embedding_count_mismatch expected={n} got={len(out)}")

    for j, v in enumerate(out):
        if len(v) != _DIM:
            raise RuntimeError(f"embedding_dim_mismatch idx={j} dim={len(v)} expected={_DIM}")

    logger.info(
        "embedder.model.summary model=%s snippets=%d secs=%.3f dim=%d",
        _MODEL,
        n,
        (t1 - t0),
        _DIM,
    )

    return out
