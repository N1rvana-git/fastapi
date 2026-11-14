"""User endpoints: registration, self-service, admin management."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status

from src.app.core.pagination import Page, PageParams, pagination_params
from src.app.modules.users import service as users_service
from src.app.modules.users.schemas import (
    UserAdminView,
    UserPublic,
    UserRegister,
    UserRoleUpdate,
)
from src.app.shared.deps import (
    AdminUser,
    CurrentUser,
    OptionalUser,
    SessionDep,
    rate_limit,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post(
    "/register",
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
    summary="Register an account",
)
async def register_user(
    request: Request,
    payload: UserRegister,
    session: SessionDep,
    actor: OptionalUser,
    _: None = Depends(rate_limit("register", limit=10, window_seconds=3600)),
) -> UserPublic:
    settings = request.app.state.settings
    allow_role_selection = settings.ALLOW_PUBLIC_ROLE_SELECTION or bool(actor and actor.is_admin)
    user = await users_service.register_user(
        session, payload, allow_role_selection=allow_role_selection
    )
    return UserPublic.model_validate(user)


@router.get("/me", response_model=UserPublic, summary="Current user profile")
async def get_me(user: CurrentUser) -> UserPublic:
    return UserPublic.model_validate(user)


@router.get(
    "/admin/all",
    response_model=Page[UserAdminView],
    summary="List users (admin)",
)
async def list_users(
    session: SessionDep,
    _admin: AdminUser,
    params: PageParams = Depends(pagination_params),
) -> Page[UserAdminView]:
    users, total = await users_service.list_users(session, skip=params.skip, limit=params.limit)
    return Page[UserAdminView].build(
        [UserAdminView.model_validate(user) for user in users], total, params
    )


@router.patch(
    "/{user_id}/role",
    response_model=UserPublic,
    summary="Change a user's role (admin)",
)
async def update_user_role(
    user_id: int,
    payload: UserRoleUpdate,
    session: SessionDep,
    _admin: AdminUser,
) -> UserPublic:
    user = await users_service.get_user_or_404(session, user_id)
    updated = await users_service.set_role(session, user, payload.role)
    return UserPublic.model_validate(updated)


@router.get("/{user_id}", response_model=UserPublic, summary="Public user profile")
async def get_user_info(user_id: int, session: SessionDep) -> UserPublic:
    user = await users_service.get_user_or_404(session, user_id)
    return UserPublic.model_validate(user)


__all__ = ["router"]
