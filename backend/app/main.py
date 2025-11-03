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
from app.api import languages as languages_api
from app.api import curricula as curricula_api
from app.api import files as files_api
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
    try:
        from app.languages.registry import get_enabled_languages_sorted, validate_registry

        validation_ok = True
        try:
            validate_registry()
        except Exception:
            validation_ok = False

        items = get_enabled_languages_sorted()
        codes = [e["code"] for e in items]
        logger.info(
            "Languages report: "
            + "source=registry "
            + f"validation_ok={validation_ok} "
            + f"count={len(items)} "
            + f"codes={','.join(codes)} "
            + "endpoints=/languages[GET]"
        )
    except Exception:
        logger.debug("Languages report skipped due to initialization issue.")
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
app.include_router(languages_api.router)
app.include_router(curricula_api.router)
app.include_router(files_api.router)


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

        parsed_provider = None
        parsed_model = None
        pattern_used = None

        label_provider = None
        label_model = None
        label_provided = bool(label)
        if label_provided:
            try:
                label_provider, label_model = parse_provider_model_from_label(label)  # type: ignore[arg-type]
                pattern_used = "label"
                logger.debug("debug/provider: parsed label successfully")
                if provider is not None or model is not None:
                    prov_match = True
                    if provider is not None:
                        entry_from_label = resolve_provider_entry(label_provider)
                        entry_from_param = resolve_provider_entry(provider)
                        prov_match = bool(entry_from_label and entry_from_param and entry_from_label.get("id") == entry_from_param.get("id"))
                    model_match = True if model is None else (label_model == model)
                    if not (prov_match and model_match):
                        logger.debug("debug/provider: param conflict between label and provider/model")
                        logger.info(
                            "debug/provider REPORT: pattern=label+params resolution=param_conflict action=400 PARAM_CONFLICT"
                        )
                        return JSONResponse(
                            status_code=400,
                            content={
                                "error": {
                                    "code": "PARAM_CONFLICT",
                                    "message": "Conflicting query params: label vs provider/model",
                                    "hint": "Send either 'label' or 'provider' + 'model'. If both are supplied, they must match exactly.",
                                }
                            },
                        )
                    else:
                        if provider is not None or model is not None:
                            logger.debug("debug/provider: redundant provider/model with label; ignoring params")
                            pattern_used = "label+redundant"
                parsed_provider = label_provider
                parsed_model = label_model
            except ValueError:
                logger.debug("debug/provider: invalid label format; will attempt provider+model params")

        if not parsed_provider or not parsed_model:
            if provider is None or model is None:
                logger.info(
                    "debug/provider REPORT: pattern=params resolution=missing_param action=400 MISSING_PARAM"
                )
                return JSONResponse(
                    status_code=400,
                    content={
                        "error": {
                            "code": "MISSING_PARAM",
                            "message": "Provide either 'label' or both 'provider' and 'model'.",
                        }
                    },
                )
            parsed_provider = provider
            parsed_model = model
            if pattern_used is None:
                pattern_used = "params"

        entry = resolve_provider_entry(parsed_provider)
        if not entry:
            known = [e.get("display_name") for e in list_providers()]
            logger.debug(f"debug/provider: unknown provider '{parsed_provider}'")
            logger.info(
                f"debug/provider REPORT: pattern={pattern_used} provider='{parsed_provider}' model='{parsed_model}' resolution=unknown_provider action=400 UNKNOWN_PROVIDER"
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
                f"debug/provider REPORT: pattern={pattern_used} provider='{entry.get('id')}' model='{parsed_model}' resolution=provider_disabled reasons={'|'.join(reasons) if reasons else ''} action=400 PROVIDER_DISABLED"
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
                f"debug/provider REPORT: pattern={pattern_used} provider='{entry.get('id')}' model='{parsed_model}' resolution=invalid_model action=400 INVALID_MODEL"
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
            f"debug/provider REPORT: pattern={pattern_used} provider='{entry.get('id')}' model='{parsed_model}' resolution=ok enabled=true validation=ok action=200 CONTINUE_FACTORY class={type(inst).__name__}"
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
