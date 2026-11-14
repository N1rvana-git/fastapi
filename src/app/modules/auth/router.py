"""Authentication endpoints (OAuth2 password flow + rotation)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm

from src.app.modules.auth.schemas import TokenResponse
from src.app.modules.users import service as users_service
from src.app.modules.users.schemas import UserPublic
from src.app.shared.deps import CurrentUser, SessionDep, rate_limit

router = APIRouter(tags=["authentication"])


@router.post("/token", response_model=TokenResponse, summary="Exchange credentials for a JWT")
async def login_for_access_token(
    request: Request,
    session: SessionDep,
    form_data: OAuth2PasswordRequestForm = Depends(),
    _: None = Depends(rate_limit("auth", limit=10, window_seconds=60)),
) -> TokenResponse:
    settings = request.app.state.settings
    user = await users_service.authenticate(session, form_data.username, form_data.password)
    token = request.app.state.container.token_service.create_access_token(user.id, role=user.role)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        role=user.role,
        user_id=user.id,
        email=user.email,
    )


@router.post("/auth/refresh", response_model=TokenResponse, summary="Rotate the access token")
async def refresh_token(request: Request, user: CurrentUser) -> TokenResponse:
    settings = request.app.state.settings
    token = request.app.state.container.token_service.create_access_token(user.id, role=user.role)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        role=user.role,
        user_id=user.id,
        email=user.email,
    )


@router.get("/auth/me", response_model=UserPublic, summary="Current authenticated user")
async def read_me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


__all__ = ["router"]
