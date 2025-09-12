from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from pathlib import Path
from contextlib import asynccontextmanager
from logging import getLogger

# Checkpointer utilities (lazy internal imports inside functions)
from app.checkpointing.postgres_checkpointer import (
    ensure_checkpointer_setup,
    inspect_checkpoint_tables,
)

logger = getLogger("supertutor.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan to run one-time startup/teardown tasks.

    We initialize the LangGraph Postgres checkpointer tables once via setup().
    """
    try:
        # Safe to call multiple times; creates tables if they do not exist.
        ensure_checkpointer_setup()
    except Exception as _:
        # Do not leak secrets/DSNs; keep log minimal.
        logger.error("Checkpointer setup skipped due to initialization error.")
    yield


app = FastAPI(title="SuperTutor Backend", lifespan=lifespan)

# Permissive CORS for early development. TODO: tighten allowed origins in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "supertutor-backend"}


@app.get("/debug/env")
def debug_env():
    """Temporary endpoint to verify env loading.

    Returns only boolean presence and the absolute env_file path. Does not
    include any secret values.
    """
    settings = get_settings()
    # Avoid returning the key; only a boolean.
    openai_present = bool(settings.OPENAI_API_KEY)
    # Expose the resolved env file path for debugging.
    # Read back the absolute env file path from settings
    env_file_path = getattr(settings, "ENV_FILE_PATH", None)
    exists = bool(env_file_path) and Path(env_file_path).exists()

    return {
        "env_file": env_file_path,
        "env_file_exists": bool(exists),
        "openai_key_present": openai_present,
    }


@app.get("/debug/checkpointer")
def debug_checkpointer():
    """Inspect LangGraph Postgres checkpointer initialization state.

    Returns only boolean/table names; never includes secrets or connection URIs.
    """
    initialized = False
    tables = []
    try:
        info = inspect_checkpoint_tables()
        tables = info.get("tables", [])
        initialized = bool(tables)
    except Exception:
        # If env/driver not configured, report uninitialized without raising.
        initialized = False
        tables = []
    return {"initialized": initialized, "existing_tables": tables}
