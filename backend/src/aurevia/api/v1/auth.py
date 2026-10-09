"""Authentication endpoints. Business rules live in ``aurevia.identity.service``."""

from __future__ import annotations

from fastapi import APIRouter, Response, status
from sqlalchemy import select

from aurevia.identity.dependencies import PrincipalDep, SessionDep, SettingsDep
from aurevia.identity.models import User
from aurevia.identity.schemas import (
    AcceptInvitationRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    SignupRequest,
    TenantResponse,
    TokenResponse,
)
from aurevia.identity.service import IdentityService, TokenPair
from aurevia.identity.tenancy import TenancyService

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED, summary="Create a tenant and owner")
async def signup(body: SignupRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    pair = await IdentityService(session, settings).signup(
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        tenant_name=body.tenant_name,
    )
    return _tokens(pair)


@router.post("/login", summary="Sign in to one tenant")
async def login(body: LoginRequest, session: SessionDep, settings: SettingsDep) -> TokenResponse:
    pair = await IdentityService(session, settings).login(
        email=body.email, password=body.password, tenant_id=body.tenant_id
    )
    return _tokens(pair)


@router.post("/invitations/accept", summary="Join a tenant with an invitation token")
async def accept_invitation(
    body: AcceptInvitationRequest, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    pair = await IdentityService(session, settings).accept_invitation(
        token=body.token, password=body.password, full_name=body.full_name
    )
    return _tokens(pair)


@router.post("/refresh", summary="Rotate a refresh token")
async def refresh(
    body: RefreshRequest, session: SessionDep, settings: SettingsDep
) -> TokenResponse:
    return _tokens(await IdentityService(session, settings).refresh(body.refresh_token))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End this session")
async def logout(body: RefreshRequest, session: SessionDep, settings: SettingsDep) -> Response:
    await IdentityService(session, settings).logout(body.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", summary="The signed-in user, tenant and role")
async def me(principal: PrincipalDep, session: SessionDep) -> MeResponse:
    user = await session.scalar(select(User).where(User.id == principal.user_id))
    tenant = await TenancyService(session, principal).current_tenant()
    assert user is not None  # noqa: S101 - get_principal verified this user is active
    return MeResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=principal.role,
        tenant=TenantResponse(id=tenant.id, name=tenant.name, slug=tenant.slug),
        permissions=sorted(p.value for p in principal.permissions),
        is_platform_admin=principal.is_platform_admin,
    )
