from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import get_settings
from pathlib import Path
from contextlib import asynccontextmanager
from logging import getLogger
from fastapi.exceptions import RequestValidationError
from app.api.responses import ok, fail
from app.api.errors import ProviderNotSupportedError, MissingApiKeyError
from app.api import providers as providers_api

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
    
    try:
        from app.providers.registry import list_providers, evaluate_provider_status

        entries = list_providers()
        # Sort by display name for deterministic report
        entries = sorted(entries, key=lambda e: (e.get("display_name") or ""))
        parts: list[str] = []
        for e in entries:
            enabled, reasons = evaluate_provider_status(e)
            name = e.get("display_name") or e.get("id")
            models = e.get("models") or []
            if enabled:
                status = "enabled"
            else:
                status = "disabled: " + "; ".join(reasons) if reasons else "disabled"
            parts.append(f"{name} ({status}) — {len(models)} models")
        if parts:
            logger.info("Providers report: " + " | ".join(parts))
    except Exception:
        
        logger.debug("Providers report skipped due to initialization issue.")
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

app.include_router(providers_api.router)


@app.get("/healthz")
def healthz():
    return ok({"service": "supertutor-backend"})


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

    return ok(
        {
            "env_file": env_file_path,
            "env_file_exists": bool(exists),
            "openai_key_present": openai_present,
        }
    )


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
    return ok({"initialized": initialized, "existing_tables": tables})


@app.get("/debug/provider")
def debug_provider(provider: str | None = None, model: str | None = None, label: str | None = None):
    """Validate provider factory construction without making network calls.

    Accepts either (provider & model) or a combined label "Provider (model)".
    Returns the normalized provider, model, and constructed class type.
    """
    try:
        from app.providers.provider_factory import (
            get_chat_model,
            normalize_provider,
            parse_provider_model_label,
        )

        if label and not (provider or model):
            provider, model = parse_provider_model_label(label)
        if not provider or not model:
            return fail("VALIDATION_ERROR", "Both provider and model must be specified (or provide a label)", status=400)

        normalized = normalize_provider(provider)
        inst = get_chat_model(provider=normalized, model=model)
        return ok({
            "provider": normalized,
            "model": model,
            "class": type(inst).__name__,
        })
    except ProviderNotSupportedError as e:
        return fail("BAD_PROVIDER", str(e), status=400)
    except MissingApiKeyError as e:
        return fail("CONFIG_ERROR", str(e), status=400)


# Global exception handlers to standardize response envelope
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        code = detail.get("code", "HTTP_ERROR")
        message = detail.get("message", str(detail))
    else:
        code = "HTTP_ERROR"
        message = str(detail)
    return fail(code, message, status=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return fail("VALIDATION_ERROR", repr(exc.errors()), status=422)


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    # Do not leak internals
    return fail("INTERNAL_ERROR", "Unexpected server error", status=500)
