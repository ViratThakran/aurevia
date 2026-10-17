"""Automatic policy check for technique candidates (WP-12.6). Runs before any person sees one.

A candidate with any flag cannot be approved until it is edited and passes. The check is
deliberately strict and simple (patterns, no model): it catches the things the voice rules
forbid outright, not matters of taste, which stay with the person reviewing.
"""

from __future__ import annotations

import re

from aurevia.learning.redaction import pattern_kinds

# The agent never claims to be human (CLAUDE.md voice rules).
_CLAIMS_HUMAN = re.compile(
    r"\b(?:i\s*(?:am|'m)\s+(?:a\s+)?(?:real\s+)?(?:person|human)"
    r"|(?:i\s*(?:am|'m)\s+)?not\s+(?:a\s+)?(?:bot|robot|machine|ai|computer)"
    r"|main\s+(?:ek\s+)?insaan\s+hoon)\b",
    re.I,
)
# Never invent guarantees.
_GUARANTEE = re.compile(
    r"\b(?:guarantee[ds]?|100\s*%|risk[- ]free|no\s+risk|assured\s+returns?)\b", re.I
)
# No false urgency or pressure.
_PRESSURE = re.compile(
    r"\b(?:only\s+today|last\s+chance|offer\s+ends|limited[- ]time|decide\s+(?:right\s+)?now"
    r"|must\s+decide|before\s+it'?s\s+too\s+late)\b",
    re.I,
)
# A redaction placeholder in what the agent says would be read out, or would stand for a real
# person's details.
_PLACEHOLDER = re.compile(r"\[(?:NAME|PHONE|EMAIL|ADDRESS|ID)_\d+\]")

FLAG_TEXT = {
    "claims_human": "Says or implies the agent is a person",
    "guarantee": "Promises a guarantee or a sure result",
    "pressure": "Uses false urgency or pressure",
    "redaction_placeholder": "Contains a redaction placeholder the agent would say",
    "personal_data": "Contains what looks like personal data",
}


def policy_flags(situation: str, says: str, goal: str, excerpt: str = "") -> list[str]:
    """The rules a candidate breaks, by name (see ``FLAG_TEXT``). Empty means it passes."""
    spoken = says
    everything = f"{situation}\n{says}\n{goal}\n{excerpt}"
    flags = []
    if _CLAIMS_HUMAN.search(spoken):
        flags.append("claims_human")
    if _GUARANTEE.search(spoken):
        flags.append("guarantee")
    if _PRESSURE.search(spoken):
        flags.append("pressure")
    if _PLACEHOLDER.search(spoken):
        flags.append("redaction_placeholder")
    if pattern_kinds(everything):
        flags.append("personal_data")
    return flags
