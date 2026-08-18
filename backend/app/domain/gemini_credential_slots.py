from __future__ import annotations


_VALID_GEMINI_CREDENTIAL_SLOTS = frozenset(
    {"", *(f"GEMINI_API_KEY_SLOT_{index}" for index in range(1, 9))}
)


def normalize_gemini_credential_slot(value: object) -> str:
    """Accept only the opaque, bounded Gemini credential-slot contract."""

    if not isinstance(value, str) or value not in _VALID_GEMINI_CREDENTIAL_SLOTS:
        raise ValueError(
            "invalid Gemini credential slot; expected empty or GEMINI_API_KEY_SLOT_1 through _8"
        )
    return value
