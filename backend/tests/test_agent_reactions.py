"""WP-11.3 agent-side reactions: off by default; when on, varied and never repeated."""

from __future__ import annotations

from aurevia.config import Settings
from aurevia.conversation.prompt import (
    PROMPT_VERSION,
    PROMPT_VERSION_REACTIONS,
    AgentProfile,
    PromptContext,
    build_system_prompt,
    prompt_version,
)
from aurevia.evaluation.style import measure, reaction_of
from aurevia.sales.state import SalesState

AGENT = AgentProfile(
    name="Meera",
    company_name="Aurevia",
    company_description="Group health cover for small firms.",
    objective="Book a call with a specialist.",
    language="en-IN",
)


def test_reactions_are_off_by_default_and_the_prompt_is_unchanged() -> None:
    assert Settings(_env_file=None).agent_reactions is False
    prompt = build_system_prompt(AGENT, SalesState.OPENING)
    assert 'Do not open with stock acknowledgements such as "I understand"' in prompt
    assert "short, natural reaction" not in prompt
    assert prompt_version(False) == PROMPT_VERSION


def test_when_on_short_varied_reactions_are_allowed_but_honesty_rules_stay() -> None:
    prompt = build_system_prompt(AGENT, SalesState.PITCH, PromptContext(reactions=True))
    assert "short, natural reaction" in prompt
    assert "never the same one twice on this call" in prompt
    assert "Never use stock acknowledgements" in prompt
    assert "Never say or imply that you are human." in prompt  # rule 8 unchanged
    assert "Ask at most one question per reply" in prompt
    assert prompt_version(True) == PROMPT_VERSION_REACTIONS != PROMPT_VERSION


def test_reaction_detection() -> None:
    assert reaction_of("Hm, okay. What matters most to you?") == "hm okay"
    assert reaction_of("Oh, nice. How many people are on the team?") == "oh nice"
    assert reaction_of("Fair enough. I can call back next week.") == "fair enough"
    assert reaction_of("Hm, got it. Shall I book Tuesday?") == "hm got it"
    assert reaction_of("Got it. Shall I book Tuesday?") is None  # a stock opener, not a reaction
    assert reaction_of("Great. Shall I book Tuesday?") is None
    assert reaction_of("We cover forty people from day one.") is None
    assert reaction_of("Okay") is None  # no sentence after it


def test_style_rewards_variety_and_flags_repeats() -> None:
    varied = measure([["Hm, okay. Tell me more.", "Oh, nice. Who decides?", "We can do Tuesday."]])
    assert round(varied.reaction_rate, 3) == 0.667 and varied.repeated_reaction_rate == 0.0
    scripted = measure([["Hm, okay. Tell me more.", "Hm, okay. Who decides?"]])
    assert scripted.reaction_rate == 1.0 and scripted.repeated_reaction_rate == 0.5
    none = measure([["We can do Tuesday."]])
    assert none.reaction_rate == 0.0 and none.repeated_reaction_rate == 0.0
