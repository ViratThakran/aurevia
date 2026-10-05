"""The signed-in principal's own tenant. There is no endpoint that takes a tenant id."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response, status

from aurevia.identity.dependencies import AdminDep, PrincipalDep, SessionDep
from aurevia.identity.schemas import ChangeRoleRequest, MemberResponse, TenantResponse
from aurevia.identity.tenancy import TenancyService

router = APIRouter(prefix="/tenant", tags=["tenant"])


@router.get("", summary="Current tenant")
async def get_tenant(principal: PrincipalDep, session: SessionDep) -> TenantResponse:
    tenant = await TenancyService(session, principal).current_tenant()
    return TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug)


@router.get("/members", summary="Active members of the current tenant")
async def list_members(principal: PrincipalDep, session: SessionDep) -> list[MemberResponse]:
    members = await TenancyService(session, principal).list_members()
    return [
        MemberResponse(
            membership_id=m.membership_id,
            user_id=m.user_id,
            email=m.email,
            full_name=m.full_name,
            role=m.role,
            joined_at=m.joined_at,
        )
        for m in members
    ]


@router.patch(
    "/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change a member's role (owner/admin)",
)
async def change_role(
    membership_id: uuid.UUID, body: ChangeRoleRequest, principal: AdminDep, session: SessionDep
) -> Response:
    await TenancyService(session, principal).change_role(membership_id, body.role)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/members/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member (owner/admin)",
)
async def remove_member(
    membership_id: uuid.UUID, principal: AdminDep, session: SessionDep
) -> Response:
    await TenancyService(session, principal).remove_member(membership_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
