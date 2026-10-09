"""Phone number normalization to E.164.

Conservative on purpose: anything that is not clearly a valid number is rejected (``None``),
and the gate blocks the call. A wrong guess here could dial the wrong person.
"""

from __future__ import annotations

import re

_E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_SEPARATORS = re.compile(r"[\s\-().]")
# Indian mobile numbers start with 6-9; landlines and special series (140/160) with 1-5.
_INDIA_NATIONAL = re.compile(r"^[1-9]\d{9}$")


def normalize_e164(raw: str | None, *, default_country_code: str = "91") -> str | None:
    """Return ``+<country><number>`` or ``None`` if ``raw`` is not a usable number."""
    if not raw:
        return None
    value = _SEPARATORS.sub("", raw.strip())
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("+"):
        return value if _E164.match(value) else None
    if not value.isdigit():
        return None
    if default_country_code == "91":
        if len(value) == 11 and value.startswith("0"):
            value = value[1:]  # trunk prefix
        elif len(value) == 12 and value.startswith("91"):
            value = value[2:]
        if _INDIA_NATIONAL.match(value):
            return "+91" + value
        return None
    candidate = f"+{default_country_code}{value.lstrip('0')}"
    return candidate if _E164.match(candidate) else None


def lookup_variants(e164: str) -> list[str]:
    """Ways the same Indian number is commonly stored, for matching free-text lead phones."""
    variants = {e164, e164.removeprefix("+")}
    if e164.startswith("+91") and len(e164) == 13:
        national = e164[3:]
        variants.update({national, "0" + national, f"+91 {national}", f"91{national}"})
    return sorted(variants)


def mask(e164: str) -> str:
    """For logs: keep the country code and last two digits only."""
    return e164[:3] + "*" * max(len(e164) - 5, 0) + e164[-2:]
