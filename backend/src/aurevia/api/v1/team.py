"""Team management: custom roles and invitations (members are under /tenant/members)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from aurevia.identity.dependencies import SessionDep, TeamDep
from aurevia.identity.models import CustomRole, Invitation, Role
from aurevia.identity.schemas import (
    CustomRoleIn,
    CustomRoleResponse,
    CustomRoleUpdate,
    InvitationCreated,
    InvitationIn,
    InvitationResponse,
)
from aurevia.identity.team import TeamService

router = APIRouter(prefix="/team", tags=["team"])


def _role(role: CustomRole) -> CustomRoleResponse:
    return CustomRoleResponse(id=role.id, name=role.name, permissions=list(role.permissions))


def _invitation(invitation: Invitation) -> InvitationResponse:
    return InvitationResponse.model_validate(invitation, from_attributes=True)


@router.get("/roles", summary="Custom roles")
async def list_roles(principal: TeamDep, session: SessionDep) -> list[CustomRoleResponse]:
    return [_role(r) for r in await TeamService(session, principal).list_roles()]


@router.post("/roles", status_code=status.HTTP_201_CREATED, summary="Create a custom role")
async def create_role(
    body: CustomRoleIn, principal: TeamDep, session: SessionDep
) -> CustomRoleResponse:
    role = await TeamService(session, principal).create_role(body.name, body.permissions)
    return _role(role)


@router.patch("/roles/{role_id}", summary="Rename a custom role or change its permissions")
async def update_role(
    role_id: uuid.UUID, body: CustomRoleUpdate, principal: TeamDep, session: SessionDep
) -> CustomRoleResponse:
    role = await TeamService(session, principal).update_role(
        role_id, name=body.name, permissions=body.permissions
    )
    return _role(role)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role nobody holds",
)
async def delete_role(role_id: uuid.UUID, principal: TeamDep, session: SessionDep) -> Response:
    await TeamService(session, principal).delete_role(role_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/invitations",
    status_code=status.HTTP_201_CREATED,
    summary="Invite someone (the token is shown once)",
)
async def invite(body: InvitationIn, principal: TeamDep, session: SessionDep) -> InvitationCreated:
    invitation, token = await TeamService(session, principal).invite(
        str(body.email), Role(body.role), body.custom_role_id
    )
    return InvitationCreated(**_invitation(invitation).model_dump(), token=token)


@router.get("/invitations", summary="Pending invitations")
async def list_invitations(principal: TeamDep, session: SessionDep) -> list[InvitationResponse]:
    return [_invitation(i) for i in await TeamService(session, principal).list_invitations()]


@router.delete(
    "/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an invitation",
)
async def revoke_invitation(
    invitation_id: uuid.UUID, principal: TeamDep, session: SessionDep
) -> Response:
    await TeamService(session, principal).revoke_invitation(invitation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
