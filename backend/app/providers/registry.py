from __future__ import annotations

from typing import Any, Dict, List, Tuple
import importlib.util as import_util

from app.core.config import get_settings


_REGISTRY: List[Dict[str, Any]] = [
    {
        "id": "openai",
        "display_name": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "import_check": "langchain_openai",
        "models": [
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4o",
            "gpt-4o-mini",
            "o3-mini",
            "o4-mini",
        ],
    },
    {
        "id": "anthropic",
        "display_name": "Anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "import_check": "langchain_anthropic",
        "models": [
            "claude-sonnet-4-5-20250929",
            "claude-3-5-sonnet-20240620",
            "claude-3-5-haiku-20241022",
        ],
    },
    {
        "id": "google",
        "display_name": "Google",
        "env_var": "GOOGLE_API_KEY",
        "import_check": "langchain_google_genai",
        "models": [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.0-pro",
            "gemini-2.0-flash",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ],
    },
    {
        "id": "deepseek",
        "display_name": "DeepSeek",
        "env_var": "DEEPSEEK_API_KEY",
        "import_check": "langchain_deepseek",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
    {
        "id": "xai",
        "display_name": "xAI",
        "env_var": "XAI_API_KEY",
        "import_check": "langchain_xai",
        "models": [
            "grok-4-0709",
            "grok-4-fast-reasoning",
            "grok-4-fast-non-reasoning",
            "grok-3",
            "grok-3-mini",
        ],
    },
]


def list_providers() -> List[Dict[str, Any]]:
    return [dict(p) for p in _REGISTRY]


def _check_env(env_var: str) -> bool:
    if not env_var:
        return False
    settings = get_settings()
    val = getattr(settings, env_var, None)
    return bool(val)


def _check_module(mod: str) -> bool:
    if not mod:
        return False
    try:
        return import_util.find_spec(mod) is not None
    except Exception:
        return False


def evaluate_provider_enabled(entry: Dict[str, Any]) -> bool:
    env_ok = _check_env(entry.get("env_var", ""))
    mod_ok = _check_module(entry.get("import_check", ""))
    return env_ok and mod_ok


def evaluate_provider_status(entry: Dict[str, Any]) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    env_var = entry.get("env_var", "")
    mod = entry.get("import_check", "")
    env_ok = _check_env(env_var)
    mod_ok = _check_module(mod)
    if not env_ok:
        reasons.append(f"missing env {env_var}")
    if not mod_ok:
        reasons.append(f"missing module {mod}")
    return (env_ok and mod_ok), reasons
