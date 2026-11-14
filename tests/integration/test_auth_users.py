"""Registration, login, RBAC and profile endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from tests.conftest import register_and_login


@pytest.mark.asyncio
async def test_register_login_and_me(client: AsyncClient) -> None:
    headers = await register_and_login(client)

    me = await client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["email"] == "user@example.com"
    assert me.json()["role"] == "user"
    assert "hashed_password" not in me.json()


@pytest.mark.asyncio
async def test_duplicate_email_conflicts(client: AsyncClient) -> None:
    await client.post(
        "/users/register", json={"email": "dup@example.com", "password": "Password123"}
    )
    response = await client.post(
        "/users/register", json={"email": "DUP@example.com", "password": "Password123"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_weak_password_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/users/register", json={"email": "weak@example.com", "password": "short"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_login_with_wrong_password(client: AsyncClient) -> None:
    await client.post("/users/register", json={"email": "x@example.com", "password": "Password123"})
    response = await client.post("/token", data={"username": "x@example.com", "password": "nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_public_registration_cannot_escalate_to_admin(client: AsyncClient) -> None:
    response = await client.post(
        "/users/register",
        json={"email": "sneaky@example.com", "password": "Password123", "role": "admin"},
    )
    assert response.status_code == 201
    assert response.json()["role"] == "user"


@pytest.mark.asyncio
async def test_email_uniqueness_is_enforced_by_the_database(
    client: AsyncClient, started_app, auth_headers: dict[str, str]
) -> None:
    """The service check can race; the partial unique index must not."""

    from sqlalchemy.exc import IntegrityError
    from src.app.modules.users.models import UserModel

    case_variant = await client.post(
        "/users/register",
        json={"email": "USER@example.com", "password": "Password123"},
    )
    assert case_variant.status_code == 409

    async with started_app.state.container.database.session() as session:
        session.add(
            UserModel(
                email="user@example.com",
                username="dupe",
                age=18,
                hashed_password="x",
                role="user",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()


@pytest.mark.asyncio
async def test_protected_endpoint_requires_token(client: AsyncClient) -> None:
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/items")).status_code == 200  # public listing


@pytest.mark.asyncio
async def test_admin_endpoints_are_forbidden_for_normal_users(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.get("/users/admin/all", headers=auth_headers)).status_code == 403
    assert (await client.get("/items/admin/secret-base", headers=auth_headers)).status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_users_and_change_roles(
    client: AsyncClient, auth_headers: dict[str, str], admin_headers: dict[str, str]
) -> None:
    listing = await client.get("/users/admin/all", headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 2

    me = await client.get("/auth/me", headers=auth_headers)
    user_id = me.json()["id"]
    promoted = await client.patch(
        f"/users/{user_id}/role", json={"role": "admin"}, headers=admin_headers
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"

    # Role changes take effect immediately (no token re-issue needed).
    assert (await client.get("/users/admin/all", headers=auth_headers)).status_code == 200


@pytest.mark.asyncio
async def test_get_public_user_profile(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    me = await client.get("/auth/me", headers=auth_headers)
    response = await client.get(f"/users/{me.json()['id']}")
    assert response.status_code == 200
    assert response.json()["email"] == "user@example.com"

    missing = await client.get("/users/99999")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_token_refresh(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.post("/auth/refresh", headers=auth_headers)
    assert response.status_code == 200
    new_token = response.json()["access_token"]
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert me.status_code == 200
