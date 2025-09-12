from __future__ import annotations

from typing import Any, Optional, Tuple

from ..core.config import get_settings
from app.api.errors import ProviderNotSupportedError, MissingApiKeyError


def _merge_params(*dicts) -> dict:
    """Merge multiple dictionaries, skipping None values and later values win.

    Ensures we don't pass duplicate/conflicting kwargs (e.g., temperature/model).
    """
    merged: dict = {}
    for d in dicts:
        for k, v in (d or {}).items():
            if v is not None:
                merged[k] = v
    return merged


def parse_provider_model_label(label: str) -> Tuple[str, str]:
    """Parse a label like "Provider (model)" into (provider, model).

    Tolerates extra whitespace and nested parentheses inside the model string.
    """
    s = (label or "").strip()
    if not s:
        raise ValueError("Empty provider/model label")
    # Find the first opening paren and the last closing paren
    try:
        i = s.index("(")
        j = s.rindex(")")
    except ValueError:
        raise ValueError("Label must be in the form 'Provider (model)'")
    prov = s[:i].strip()
    model = s[i + 1 : j].strip()
    if not prov or not model:
        raise ValueError("Both provider and model must be specified in label")
    return prov, model


def normalize_provider(p: str) -> str:
    """Normalize provider aliases to canonical keys."""
    key = (p or "").strip().lower()
    mapping = {
        "openai": "openai",
        "anthropic": "anthropic",
        "google": "google",
        "gemini": "google",
        "deepseek": "deepseek",
        "xai": "xai",
        "grok": "xai",
        "openrouter": "openrouter",
    }
    if key in mapping:
        return mapping[key]
    return key


def get_chat_model(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    label: Optional[str] = None,
    **kwargs,
) -> Any:
    """Return a LangChain chat model instance for the selected provider.

    This factory performs lazy imports to avoid import-time errors if optional
    provider packages are not installed yet. It does not make any network calls.

    Args:
        provider: One of {"openai", "anthropic", "google", "deepseek", "xai", "openrouter"}
        model: The model identifier to use (e.g., "gpt-4o-mini"). If omitted, supply label.
        label: Combined label like "Provider (model)".
        **kwargs: Additional keyword arguments forwarded to the chat model

    Raises:
        RuntimeError: If the required API key for the provider is missing.
        ValueError: If an unknown provider is specified.
    """
    if label and not (provider or model):
        prov_from_label, model_from_label = parse_provider_model_label(label)
        provider = prov_from_label
        model = model_from_label

    if not provider or not model:
        raise ValueError("Both provider and model must be specified (or provide a label)")

    p = normalize_provider(provider)
    settings = get_settings()

    if p == "openai":
        from langchain_openai import ChatOpenAI

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.OPENAI_API_KEY
        if not api_key:
            raise MissingApiKeyError("Missing OPENAI_API_KEY for provider 'openai'")
        # Build params safely: defaults + enforced model + user overrides (no duplicates)
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)  # model is provided explicitly via arg
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # Note: params includes temperature/model; do not duplicate in call signature
        return ChatOpenAI(api_key=api_key, **params)

    if p == "anthropic":
        from langchain_anthropic import ChatAnthropic

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.ANTHROPIC_API_KEY
        if not api_key:
            raise MissingApiKeyError("Missing ANTHROPIC_API_KEY for provider 'anthropic'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # params already carries temperature/model
        return ChatAnthropic(api_key=api_key, **params)

    if p == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.GOOGLE_API_KEY
        if not api_key:
            raise MissingApiKeyError("Missing GOOGLE_API_KEY for provider 'google'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # params already carries temperature/model
        return ChatGoogleGenerativeAI(api_key=api_key, **params)

    if p == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.DEEPSEEK_API_KEY
        if not api_key:
            raise MissingApiKeyError("Missing DEEPSEEK_API_KEY for provider 'deepseek'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # params already carries temperature/model
        return ChatDeepSeek(api_key=api_key, **params)

    if p == "xai":
        from langchain_xai import ChatXAI

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.XAI_API_KEY
        if not api_key:
            raise MissingApiKeyError("Missing XAI_API_KEY for provider 'xai'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # params already carries temperature/model
        return ChatXAI(api_key=api_key, **params)

    if p == "openrouter":
        # OpenRouter is OpenAI-compatible. Use ChatOpenAI with base_url and default headers.
        # See OpenRouter docs: set base_url https://openrouter.ai/api/v1 and optional headers.
        from langchain_openai import ChatOpenAI

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.OPENROUTER_API_KEY
        if not api_key:
            raise MissingApiKeyError("Missing OPENROUTER_API_KEY for provider 'openrouter'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)

        headers = {}
        if settings.OPENROUTER_SITE_URL:
            headers["HTTP-Referer"] = settings.OPENROUTER_SITE_URL
        if settings.OPENROUTER_APP_TITLE:
            headers["X-Title"] = settings.OPENROUTER_APP_TITLE

        return ChatOpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers=headers or None,
            **params,
        )

    raise ProviderNotSupportedError(f"Unknown provider: {provider}")
