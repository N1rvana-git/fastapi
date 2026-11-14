"""User DTO validation and role guard."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from src.app.modules.users.schemas import (
    UserAdminView,
    UserPublic,
    UserRegister,
    ensure_valid_role,
)


def test_password_is_limited_by_bcrypt_bytes() -> None:
    with pytest.raises(ValidationError, match="72 bytes"):
        UserRegister(email="a@example.com", password="密" * 30)


def test_username_is_trimmed_and_password_ok() -> None:
    payload = UserRegister(email="a@example.com", password="Password123", username="  alice  ")
    assert payload.username == "alice"


def test_public_models_read_orm_attributes() -> None:
    row = SimpleNamespace(id=1, username="alice", email="a@example.com", role="user")
    public = UserPublic.model_validate(row)
    assert public.id == 1
    admin = UserAdminView.model_validate(row)
    assert admin.phone is None


def test_ensure_valid_role() -> None:
    assert ensure_valid_role("admin") == "admin"
    with pytest.raises(ValueError, match="invalid role"):
        ensure_valid_role("root")
