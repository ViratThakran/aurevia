"""Phase 8: built-in roles map to fixed permission sets; custom roles replace member rights."""

from __future__ import annotations

from aurevia.conversation.prompt import AgentProfile, build_system_prompt
from aurevia.identity.models import Role
from aurevia.identity.permissions import (
    ALL_PERMISSIONS,
    Permission,
    parse_permissions,
    permissions_for,
)
from aurevia.sales.state import SalesState


def test_builtin_roles() -> None:
    assert permissions_for(Role.OWNER, None) == ALL_PERMISSIONS
    assert permissions_for(Role.ADMIN, None) == ALL_PERMISSIONS
    member = permissions_for(Role.MEMBER, None)
    assert Permission.CALLS_PLACE in member and Permission.TEAM_MANAGE not in member
    assert Permission.LEADS_PRIVACY not in member and Permission.AUDIT_READ not in member


def test_custom_roles_apply_to_members_only() -> None:
    custom = frozenset({Permission.ANALYTICS_READ})
    assert permissions_for(Role.MEMBER, custom) == custom
    assert permissions_for(Role.ADMIN, custom) == ALL_PERMISSIONS


def test_unknown_stored_permissions_are_ignored() -> None:
    assert parse_permissions(["calls.place", "rocket.launch"]) == {Permission.CALLS_PLACE}


def _agent(**setup: object) -> AgentProfile:
    return AgentProfile(
        name="Aria",
        company_name="Acme",
        company_description="Group health cover.",
        objective="Book a meeting.",
        language="en-IN",
        **setup,  # type: ignore[arg-type]
    )


def test_agent_setup_reaches_the_prompt_only_when_configured() -> None:
    bare = build_system_prompt(_agent(), SalesState.DISCOVERY)
    assert "# Personality" not in bare and "# What to find out" not in bare
    full = build_system_prompt(
        _agent(
            personality="Warm\nand concise.",
            qualification_questions=("How many employees?", "  "),
            objection_guidance="On price, explain claims support.",
            escalation_guidance="Hand over for claims in progress.",
        ),
        SalesState.DISCOVERY,
    )
    assert "# Personality\nWarm and concise." in full  # flattened: no new prompt sections
    assert "- How many employees?" in full and "-   " not in full
    assert "# Handling objections" in full and "# When to bring in a colleague" in full
