from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from pathlib import Path

app = FastAPI(title="SuperTutor Backend")

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
