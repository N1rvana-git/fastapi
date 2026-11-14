"""User API contracts (DTOs) - never the ORM model."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from src.app.modules.users.models import ROLE_USER, VALID_ROLES

Password = Annotated[
    str, Field(min_length=8, max_length=72, description="8-72 bytes (bcrypt limit)")
]


class UserRegister(BaseModel):
    email: EmailStr
    password: Password
    username: str | None = Field(default=None, min_length=2, max_length=64)
    role: Literal["user", "admin"] = ROLE_USER

    @field_validator("password")
    @classmethod
    def _password_bytes(cls, value: str) -> str:
        # bcrypt silently truncates at 72 bytes, which would make long passwords
        # weaker than they look; reject instead of silently downgrading.
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 bytes")
        return value

    @field_validator("username")
    @classmethod
    def _clean_username(cls, value: str | None) -> str | None:
        return value.strip() if value else value


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    role: str = ROLE_USER
    created_at: object | None = None


class UserAdminView(UserPublic):
    phone: str | None = None
    feishu_open_id: str | None = None


class UserRoleUpdate(BaseModel):
    role: Literal["user", "admin"]


def ensure_valid_role(role: str) -> str:
    if role not in VALID_ROLES:
        raise ValueError(f"invalid role: {role}")
    return role


__all__ = ["UserAdminView", "UserPublic", "UserRegister", "UserRoleUpdate", "ensure_valid_role"]
