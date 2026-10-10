"""Word error rate: how much of what was said the transcript got wrong (lower is better).

WER = (substitutions + deletions + insertions) / words actually said, after lower-casing and
removing punctuation. Used by the simulator, which knows exactly what the prospect said.
"""

from __future__ import annotations

import re

_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "ten": "10", "forty": "40",
}  # fmt: skip


def normalize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9']+", text.lower().replace(chr(0x2019), "'"))
    return [_NUMBER_WORDS.get(w, w) for w in words]


def word_error_rate(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, start=1):
        current = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, start=1):
            current[j] = min(
                previous[j] + 1,  # deletion
                current[j - 1] + 1,  # insertion
                previous[j - 1] + (r != h),  # substitution or match
            )
        previous = current
    return previous[-1] / len(ref)
