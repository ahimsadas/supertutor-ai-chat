from __future__ import annotations

"""
Static registry for supported languages. No side effects on import.
Consumers may call `validate_registry()` explicitly if they want to verify integrity.
"""

import re
from typing import List, Set, TypedDict, cast


class Language(TypedDict):
    code: str
    name: str
    rtl: bool
    enabled: bool
    sort_order: int


# Single source of truth for language options used by the UI and validation.
LANGUAGES: List[Language] = [
    {
        "code": "auto",
        "name": "Auto (match input)",
        "rtl": False,
        "enabled": True,
        "sort_order": 0,
    },
    {
        "code": "en",
        "name": "English",
        "rtl": False,
        "enabled": True,
        "sort_order": 1,
    },
    {
        "code": "hi",
        "name": "Hindi",
        "rtl": False,
        "enabled": True,
        "sort_order": 2,
    },
    {
        "code": "ta",
        "name": "Tamil",
        "rtl": False,
        "enabled": True,
        "sort_order": 3,
    },
]


def get_languages() -> List[Language]:
    """Return a shallow copy of the registry list."""
    return [cast(Language, entry.copy()) for entry in LANGUAGES]


def get_language_codes() -> Set[str]:
    return {entry["code"] for entry in LANGUAGES}


def get_enabled_languages_sorted() -> List[Language]:
    enabled = [entry for entry in LANGUAGES if entry["enabled"] is True]
    ordered = sorted(enabled, key=lambda e: (e["sort_order"], e["name"]))
    return [cast(Language, entry.copy()) for entry in ordered]


def validate_registry() -> None:
    """Validate internal invariants of the registry.

    Validations:
    - codes are lowercase and match ^[A-Za-z0-9-]{1,15}$
    - codes are unique
    - sort_order is int
    - required keys exist with correct types
    """
    code_re = re.compile(r"^[A-Za-z0-9-]{1,15}$")
    seen: Set[str] = set()

    for idx, lang in enumerate(LANGUAGES):
        # Required keys
        required = {"code", "name", "rtl", "enabled", "sort_order"}
        missing = required.difference(lang.keys())
        if missing:
            raise ValueError(f"missing keys at index {idx}: {sorted(missing)}")

        code = lang["code"]
        name = lang["name"]
        rtl = lang["rtl"]
        enabled = lang["enabled"]
        sort_order = lang["sort_order"]

        # Types
        if not isinstance(code, str):
            raise ValueError(f"code must be str at index {idx}")
        if not isinstance(name, str):
            raise ValueError(f"name must be str for code '{code}'")
        if type(rtl) is not bool:  # avoid bool-as-int confusion
            raise ValueError(f"rtl must be bool for code '{code}'")
        if type(enabled) is not bool:
            raise ValueError(f"enabled must be bool for code '{code}'")
        if not isinstance(sort_order, int) or isinstance(sort_order, bool):
            raise ValueError(f"sort_order must be int for code '{code}'")

        # Code constraints
        if code != code.lower():
            raise ValueError(f"code must be lowercase: '{code}'")
        if not code_re.fullmatch(code):
            raise ValueError(f"invalid code pattern: '{code}'")
        if code in seen:
            raise ValueError(f"duplicate code: '{code}'")
        seen.add(code)

    # No return on success


if __name__ == "__main__":
    enabled_sorted_codes = [e["code"] for e in get_enabled_languages_sorted()]
    ok = True
    err = None
    try:
        validate_registry()
    except Exception as e:  # pragma: no cover - convenience output only
        ok = False
        err = str(e)

    print("LANGUAGES_COUNT:", len(LANGUAGES))
    print("ENABLED_SORTED:", enabled_sorted_codes)
    print("VALIDATION_OK:", ok)
    if not ok and err is not None:
        print("VALIDATION_ERROR:", err)
