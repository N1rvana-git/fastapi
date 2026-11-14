"""Authentication DTOs."""

from __future__ import annotations

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    user_id: int
    email: str | None = None


class TokenPayload(BaseModel):
    sub: str
    role: str = "user"
    exp: int | None = None


__all__ = ["TokenPayload", "TokenResponse"]
