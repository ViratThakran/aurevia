"""WP-11.5: say amounts, phone numbers and dates the way people do. Built early, off by default.

Applied only to the text sent to the voice (``AUREVIA_NATURAL_SPEECH``); the transcript and the
model keep the original words. The prompt already asks the model to write numbers as spoken;
this is the safety net for when it does not.

- Rupee amounts in Indian numbering: "₹1,50,000" -> "one lakh fifty thousand rupees".
- Indian mobile numbers digit by digit in groups: "+91 98765 43210" -> "plus nine one, nine
  eight seven six five, four three two one zero".
- Numeric dates (day first, as in India): "17/10/2026" -> "17 October 2026".
- A pronunciation list (``AUREVIA_PRONUNCIATIONS``), e.g. {"Aurevia": "Aw-REE-vee-uh"}:
  whole-word, case-insensitive respellings.

Anything else is left exactly as written.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterable, AsyncIterator, Mapping

_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS = [
    "_",
    "_",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
_DIGITS = dict(zip("0123456789", _ONES[:10], strict=True))


def _below_hundred(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] + (f"-{_ONES[ones]}" if ones else "")


def _below_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{_ONES[hundreds]} hundred")
    if rest:
        parts.append(_below_hundred(rest))
    return " ".join(parts) or "zero"


def indian_words(n: int) -> str:
    """A whole number in Indian English: 150000 -> "one lakh fifty thousand"."""
    if n < 0:
        return "minus " + indian_words(-n)
    if n < 1000:
        return _below_thousand(n)
    parts = []
    crore, n = divmod(n, 10_000_000)
    lakh, n = divmod(n, 100_000)
    thousand, n = divmod(n, 1000)
    if crore:
        parts.append(f"{indian_words(crore)} crore")
    if lakh:
        parts.append(f"{_below_hundred(lakh)} lakh")
    if thousand:
        parts.append(f"{_below_hundred(thousand)} thousand")
    if n:
        parts.append(_below_thousand(n))
    return " ".join(parts)


_AMOUNT = re.compile(
    r"(?:₹\s?|\b(?:Rs\.?|INR)\s?)(\d{1,3}(?:,\d{2,3})*|\d+)(?:\.(\d{1,2}))?(?![\d,])",
    re.IGNORECASE,
)
_PHONE = re.compile(r"(?<![\w+])(\+91[\s-]?|0)?([6-9]\d{4})[\s-]?(\d{5})(?![\w])")
_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")


def _amount(match: re.Match[str]) -> str:
    rupees = int(match.group(1).replace(",", ""))
    paise = int((match.group(2) or "0").ljust(2, "0"))
    words = f"{indian_words(rupees)} rupee{'s' if rupees != 1 else ''}"
    if paise:
        words += f" and {indian_words(paise)} paise"
    return words


def _phone(match: re.Match[str]) -> str:
    prefix = match.group(1) or ""
    groups = [" ".join(_DIGITS[d] for d in g) for g in (match.group(2), match.group(3))]
    spoken = ", ".join(groups)
    if prefix.startswith("+"):
        return f"plus nine one, {spoken}"
    if prefix.startswith("0"):
        return f"zero, {spoken}"
    return spoken


def _date(match: re.Match[str]) -> str:
    day, month, year = (int(g) for g in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return match.group(0)
    return f"{day} {_MONTHS[month - 1]} {year}"


def speak_naturally(text: str, pronunciations: Mapping[str, str] | None = None) -> str:
    text = _AMOUNT.sub(_amount, text)
    text = _PHONE.sub(_phone, text)
    text = _DATE.sub(_date, text)
    for word, respelling in (pronunciations or {}).items():
        text = re.sub(rf"\b{re.escape(word)}\b", respelling, text, flags=re.IGNORECASE)
    return text


async def natural_chunks(
    chunks: AsyncIterable[str], pronunciations: Mapping[str, str] | None = None
) -> AsyncIterator[str]:
    """Shape streamed text without cutting a number or name in two: text is held back until a
    space, then the complete words are shaped and sent on. The rest goes out at the end."""
    pending = ""
    async for chunk in chunks:
        pending += chunk
        cut = max(pending.rfind(" "), pending.rfind("\n"))
        if cut < 0:
            continue
        ready, pending = pending[: cut + 1], pending[cut + 1 :]
        # A phone number or amount may still continue after the space ("98765 43210").
        tail = re.search(r"(?:₹|Rs\.?|INR|\+91|\d)[\d\s,.-]*$", ready, re.IGNORECASE)
        if tail:
            ready, pending = ready[: tail.start()], ready[tail.start() :] + pending
        if ready:
            yield speak_naturally(ready, pronunciations)
    if pending:
        yield speak_naturally(pending, pronunciations)
