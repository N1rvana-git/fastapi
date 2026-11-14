"""User service guards that do not need a database."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from src.app.core.exceptions import ConflictError, NotFoundError, UnauthorizedError
from src.app.modules.users import service


class FakeSession:
    async def commit(self) -> None:
        return None

    async def refresh(self, _obj: Any) -> None:
        return None


@pytest.mark.asyncio
async def test_get_user_or_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(_session: Any, _user_id: int) -> None:
        return None

    monkeypatch.setattr(service.repository, "get_by_id", missing)
    with pytest.raises(NotFoundError):
        await service.get_user_or_404(FakeSession(), 42)


@pytest.mark.asyncio
async def test_authenticate_unknown_user(monkeypatch: pytest.MonkeyPatch) -> None:
    async def missing(_session: Any, _email: str) -> None:
        return None

    monkeypatch.setattr(service.repository, "get_by_email", missing)
    with pytest.raises(UnauthorizedError):
        await service.authenticate(FakeSession(), "nobody@example.com", "Password123")


@pytest.mark.asyncio
async def test_bind_account_rejects_owner_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    async def owned(_session: Any, _open_id: str) -> Any:
        return SimpleNamespace(id=2)

    monkeypatch.setattr(service.repository, "get_by_feishu_open_id", owned)
    user = SimpleNamespace(id=1, feishu_open_id=None)
    with pytest.raises(ConflictError):
        await service.bind_feishu_account(FakeSession(), user, "ou_taken")


@pytest.mark.asyncio
async def test_set_role_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    user = SimpleNamespace(id=1, role="user")
    updated = await service.set_role(FakeSession(), user, "admin")
    assert updated.role == "admin"
