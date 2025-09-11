from __future__ import annotations

from typing import Any, Optional

from ..core.config import get_settings


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


def get_chat_model(provider: str, model: str, **kwargs) -> Any:
    """Return a LangChain chat model instance for the selected provider.

    This factory performs lazy imports to avoid import-time errors if optional
    provider packages are not installed yet. It does not make any network calls.

    Args:
        provider: One of {"openai", "anthropic", "google", "deepseek", "xai"}
        model: The model identifier to use (e.g., "gpt-4o-mini")
        **kwargs: Additional keyword arguments forwarded to the chat model

    Raises:
        RuntimeError: If the required API key for the provider is missing.
        ValueError: If an unknown provider is specified.
    """
    p = provider.lower().strip()
    settings = get_settings()

    if p == "openai":
        from langchain_openai import ChatOpenAI

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.OPENAI_API_KEY
        if not api_key:
            raise RuntimeError("Missing OPENAI_API_KEY for provider 'openai'")
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
            raise RuntimeError("Missing ANTHROPIC_API_KEY for provider 'anthropic'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # params already carries temperature/model
        return ChatAnthropic(api_key=api_key, **params)

    if p == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        api_key: Optional[str] = kwargs.pop("google_api_key", None) or settings.GOOGLE_API_KEY
        if not api_key:
            raise RuntimeError("Missing GOOGLE_API_KEY for provider 'google'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # params already carries temperature/model
        return ChatGoogleGenerativeAI(google_api_key=api_key, **params)

    if p == "deepseek":
        from langchain_deepseek import ChatDeepSeek

        api_key: Optional[str] = kwargs.pop("api_key", None) or settings.DEEPSEEK_API_KEY
        if not api_key:
            raise RuntimeError("Missing DEEPSEEK_API_KEY for provider 'deepseek'")
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
            raise RuntimeError("Missing XAI_API_KEY for provider 'xai'")
        defaults = {"temperature": 0}
        user_overrides = dict(kwargs)
        user_overrides.pop("model", None)
        params = _merge_params(defaults, {"model": model}, user_overrides)
        # params already carries temperature/model
        return ChatXAI(api_key=api_key, **params)

    raise ValueError(f"Unknown provider: {provider}")
