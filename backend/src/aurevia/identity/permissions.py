"""Permissions (Phase 8): what a member may do, checked server-side on every endpoint.

Built-in roles map to fixed permission sets. Owners and admins hold every permission; what
only an owner may do (create or change owners) stays a role rule in ``tenancy.py``. A member
with a custom role holds exactly that role's permissions.

Nobody can grant more than they hold: assigning a role, or creating one, requires holding
every permission it contains.
"""

from __future__ import annotations

from enum import StrEnum

from aurevia.identity.models import Role


class Permission(StrEnum):
    CALLS_PLACE = "calls.place"  # browser test calls, outbound calls, campaign "call next"
    LEADS_MANAGE = "leads.manage"  # create, edit and import leads; consent; memories
    LEADS_PRIVACY = "leads.privacy"  # export or erase a person's data (DPDP)
    CAMPAIGNS_MANAGE = "campaigns.manage"  # campaigns, their lead lists and auto-dialing
    AGENTS_MANAGE = "agents.manage"
    NUMBERS_MANAGE = "numbers.manage"  # caller ids and test numbers
    COMPLIANCE_MANAGE = "compliance.manage"  # policy version choice and tightening
    TEAM_MANAGE = "team.manage"  # invitations, roles, members
    AUDIT_READ = "audit.read"
    ANALYTICS_READ = "analytics.read"  # analytics and usage/cost


ALL_PERMISSIONS = frozenset(Permission)

BUILTIN_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.OWNER: ALL_PERMISSIONS,
    Role.ADMIN: ALL_PERMISSIONS,
    Role.MEMBER: frozenset(
        {Permission.CALLS_PLACE, Permission.LEADS_MANAGE, Permission.ANALYTICS_READ}
    ),
}


def permissions_for(role: Role, custom: frozenset[Permission] | None) -> frozenset[Permission]:
    """A member with a custom role has exactly its permissions; everyone else, their role's."""
    if role == Role.MEMBER and custom is not None:
        return custom
    return BUILTIN_PERMISSIONS[role]


def parse_permissions(values: list[str] | tuple[str, ...]) -> frozenset[Permission]:
    """Stored permission names; unknown names (e.g. removed in a later version) are ignored."""
    known = {p.value for p in Permission}
    return frozenset(Permission(v) for v in values if v in known)
