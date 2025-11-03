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
import re
from fastapi.responses import JSONResponse
from app.providers.registry import (
    list_providers,
    evaluate_provider_enabled,
    evaluate_provider_status,
)

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


def parse_provider_model_from_label(label: str) -> tuple[str, str]:
    pattern = re.compile(r"^\s*(?P<provider>[^()]+?)\s*\(\s*(?P<model>[^()]+)\s*\)\s*$")
    m = pattern.match(label or "")
    if not m:
        raise ValueError("Invalid label format")
    prov = (m.group("provider") or "").strip()
    model = (m.group("model") or "").strip()
    if not prov or not model:
        raise ValueError("Invalid label format")
    return prov, model


def resolve_provider_entry(name_or_id: str):
    q = (name_or_id or "").strip().lower()
    if not q:
        return None
    entries = list_providers()
    for e in entries:
        if (e.get("id") or "").lower() == q:
            return e
        if (e.get("display_name") or "").lower() == q:
            return e
    return None


@app.get("/debug/provider")
def debug_provider(provider: str | None = None, model: str | None = None, label: str | None = None):
    """Validate provider factory construction without making network calls.

    Accepts either (provider & model) or a combined label "Provider (model)".
    Returns the normalized provider, model, and constructed class type.
    """
    try:
        from app.providers.provider_factory import get_chat_model

        parsed_provider = provider
        parsed_model = model

        used_label = False
        if label:
            try:
                lp, lm = parse_provider_model_from_label(label)
                parsed_provider, parsed_model = lp, lm
                used_label = True
                logger.debug("debug/provider: parsed via label")
            except ValueError:
                logger.debug("debug/provider: label parse failed; attempting provider+model params")
                pass

        if not parsed_provider or not parsed_model:
            logger.info(
                f"debug/provider REPORT: provider='{parsed_provider}' model='{parsed_model}' resolution=none enabled=n/a validation=invalid_input action=400 VALIDATION_ERROR"
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "VALIDATION_ERROR",
                        "message": "Both provider and model must be specified (or provide a valid label)",
                    }
                },
            )

        entry = resolve_provider_entry(parsed_provider)
        if not entry:
            known = [e.get("display_name") for e in list_providers()]
            logger.debug(f"debug/provider: unknown provider '{parsed_provider}'")
            logger.info(
                f"debug/provider REPORT: provider='{parsed_provider}' model='{parsed_model}' resolution=not_found enabled=n/a validation=unknown_provider action=400 UNKNOWN_PROVIDER"
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "UNKNOWN_PROVIDER",
                        "message": f"Unknown provider '{parsed_provider}'",
                        "known_providers": known,
                    }
                },
            )

        enabled = evaluate_provider_enabled(entry)
        if not enabled:
            _, reasons = evaluate_provider_status(entry)
            logger.debug(f"debug/provider: provider disabled — {'; '.join(reasons) if reasons else 'unknown'}")
            logger.info(
                f"debug/provider REPORT: provider='{entry.get('id')}' model='{parsed_model}' resolution=ok enabled=false reasons={'|'.join(reasons) if reasons else ''} validation=provider_disabled action=400 PROVIDER_DISABLED"
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "PROVIDER_DISABLED",
                        "message": f"Provider '{entry.get('display_name')}' is disabled",
                        "reasons": reasons or [],
                    }
                },
            )

        allowed = entry.get("models") or []
        if parsed_model not in allowed:
            logger.debug(
                f"debug/provider: invalid model '{parsed_model}' for provider '{entry.get('id')}'"
            )
            logger.info(
                f"debug/provider REPORT: provider='{entry.get('id')}' model='{parsed_model}' resolution=ok enabled=true validation=invalid_model action=400 INVALID_MODEL"
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "INVALID_MODEL",
                        "message": f"Model '{parsed_model}' is not in the allow-list for provider '{entry.get('display_name')}'",
                        "provider": entry.get("id"),
                        "requested_model": parsed_model,
                        "allowed_models": allowed,
                    }
                },
            )

        inst = get_chat_model(provider=entry.get("id"), model=parsed_model)
        logger.debug(
            f"debug/provider: validated provider='{entry.get('id')}', model='{parsed_model}' — constructing factory"
        )
        logger.info(
            f"debug/provider REPORT: provider='{entry.get('id')}' model='{parsed_model}' resolution=ok enabled=true validation=ok action=200 CONTINUE_FACTORY class={type(inst).__name__}"
        )
        return ok({
            "provider": entry.get("id"),
            "model": parsed_model,
            "class": type(inst).__name__,
        })
    except ProviderNotSupportedError as e:
        logger.debug(f"debug/provider: factory error — {str(e)}")
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "BAD_PROVIDER", "message": str(e)}},
        )
    except MissingApiKeyError as e:
        logger.debug(f"debug/provider: config error — {str(e)}")
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "CONFIG_ERROR", "message": str(e)}},
        )


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
