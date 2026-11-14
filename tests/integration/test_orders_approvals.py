"""Purchase flow, stock safety and the human-approval workflow."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from src.app.core.exceptions import ApprovalRequiredError, BusinessRuleViolation, OutOfStockError
from src.app.modules.chat import approvals
from src.app.modules.orders import repository as orders_repository
from src.app.modules.orders import service as orders_service
from src.app.modules.users import repository as users_repository
from tests.conftest import create_listing


async def _user(session, email: str):
    user = await users_repository.get_by_email(session, email)
    assert user is not None
    return user


@pytest.mark.asyncio
async def test_buy_decrements_stock_and_creates_order(
    client: AsyncClient, auth_headers: dict[str, str], second_user_headers: dict[str, str]
) -> None:
    created = await create_listing(client, auth_headers, price=100.0, inventory=2)

    response = await client.post(f"/items/{created['id']}/buy", headers=second_user_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["order_id"] > 0
    assert body["quantity"] == 1
    assert body["remaining_inventory"] == 1

    item = await client.get(f"/items/{created['id']}")
    assert item.json()["inventory"] == 1
    assert item.json()["is_sold"] is False


@pytest.mark.asyncio
async def test_oversell_is_rejected(
    client: AsyncClient, auth_headers: dict[str, str], second_user_headers: dict[str, str]
) -> None:
    created = await create_listing(client, auth_headers, inventory=1)

    first = await client.post(f"/items/{created['id']}/buy", headers=second_user_headers)
    assert first.status_code == 200
    second = await client.post(f"/items/{created['id']}/buy", headers=second_user_headers)
    assert second.status_code == 400
    assert second.json()["error"]["code"] == "OUT_OF_STOCK"

    item = await client.get(f"/items/{created['id']}")
    assert item.json()["inventory"] == 0
    assert item.json()["is_sold"] is True


@pytest.mark.asyncio
async def test_cannot_buy_own_listing(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await create_listing(client, auth_headers)
    response = await client.post(f"/items/{created['id']}/buy", headers=auth_headers)
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_buy_is_idempotent(
    client: AsyncClient, auth_headers: dict[str, str], second_user_headers: dict[str, str]
) -> None:
    created = await create_listing(client, auth_headers, inventory=2)
    headers = {**second_user_headers, "X-Idempotency-Key": "buy-1"}

    first = await client.post(f"/items/{created['id']}/buy", headers=headers)
    second = await client.post(f"/items/{created['id']}/buy", headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["order_id"] == second.json()["order_id"]
    assert second.headers.get("X-Idempotent-Replay") == "true"
    item = await client.get(f"/items/{created['id']}")
    assert item.json()["inventory"] == 1


@pytest.mark.asyncio
async def test_long_idempotency_key_is_hashed_before_storage(
    client: AsyncClient, auth_headers: dict[str, str], second_user_headers: dict[str, str]
) -> None:
    created = await create_listing(client, auth_headers, inventory=2)
    headers = {**second_user_headers, "X-Idempotency-Key": "k" * 128}

    first = await client.post(f"/items/{created['id']}/buy", headers=headers)
    second = await client.post(f"/items/{created['id']}/buy", headers=headers)

    assert first.status_code == 200, first.text
    assert first.json()["order_id"] == second.json()["order_id"]


@pytest.mark.asyncio
async def test_approval_threshold_blocks_large_orders_at_service_level(
    client: AsyncClient,
    started_app,
    auth_headers: dict[str, str],
    second_user_headers: dict[str, str],
) -> None:
    created = await create_listing(client, auth_headers, price=1500.0, inventory=3)
    container = started_app.state.container

    async with container.database.session() as session:
        buyer = await _user(session, "buyer2@example.com")
        with pytest.raises(ApprovalRequiredError) as excinfo:
            await orders_service.purchase(
                session,
                item_id=created["id"],
                buyer=buyer,
                settings=container.settings,
                require_approval=True,
            )
    details = excinfo.value.details
    assert details["amount"] == 1500.0
    assert details["threshold"] == container.settings.AGENT_APPROVAL_THRESHOLD

    # Nothing was reserved while waiting for approval.
    item = await client.get(f"/items/{created['id']}")
    assert item.json()["inventory"] == 3


@pytest.mark.asyncio
async def test_resume_endpoint_completes_the_suspended_purchase(
    client: AsyncClient,
    started_app,
    auth_headers: dict[str, str],
    second_user_headers: dict[str, str],
) -> None:
    created = await create_listing(client, auth_headers, price=1500.0, inventory=3)
    container = started_app.state.container

    async with container.database.session() as session:
        buyer = await _user(session, "buyer2@example.com")
        try:
            await orders_service.purchase(
                session,
                item_id=created["id"],
                buyer=buyer,
                settings=container.settings,
                require_approval=True,
            )
        except ApprovalRequiredError as exc:
            details = exc.details
        approval = await approvals.request_approval(
            session,
            thread_id="u2:main",
            user_id=buyer.id,
            action="create_order",
            payload=details,
            reason="超过自动授权额度",
            settings=container.settings,
        )

    status = await client.get("/items/ai/threads/u2:main/status", headers=second_user_headers)
    assert status.status_code == 200
    assert status.json()["is_interrupted"] is True

    resume = await client.post(
        "/items/ai/threads/u2:main/resume",
        json={"approved": True, "approval_id": approval.id},
        headers=second_user_headers,
    )
    assert resume.status_code == 200, resume.text
    assert resume.json()["order_id"] > 0

    item = await client.get(f"/items/{created['id']}")
    assert item.json()["inventory"] == 2

    async with container.database.session() as session:
        order = await orders_repository.get_by_idempotency_key(session, f"approval:{approval.id}")
    assert order is not None

    replay = await client.post(
        "/items/ai/threads/u2:main/resume",
        json={"approved": True, "approval_id": approval.id},
        headers=second_user_headers,
    )
    assert replay.status_code == 409


@pytest.mark.asyncio
async def test_resume_requires_a_pending_approval(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/items/ai/threads/u1:main/resume",
        json={"approved": True},
        headers=auth_headers,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_expired_approvals_are_closed(
    client: AsyncClient,
    started_app,
    auth_headers: dict[str, str],
    second_user_headers: dict[str, str],
) -> None:
    created = await create_listing(client, auth_headers, price=1500.0)
    container = started_app.state.container

    async with container.database.session() as session:
        buyer = await _user(session, "buyer2@example.com")
        approval = await approvals.request_approval(
            session,
            thread_id="u2:stale",
            user_id=buyer.id,
            action="create_order",
            payload={"item_id": created["id"], "quantity": 1, "address": "详细地址"},
            reason="stale",
            settings=container.settings,
        )
        approval.expires_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
        expired = await approvals.expire_stale(session)
        assert expired == 1

    resume = await client.post(
        "/items/ai/threads/u2:stale/resume",
        json={"approved": True, "approval_id": approval.id},
        headers=second_user_headers,
    )
    assert resume.status_code == 409


@pytest.mark.asyncio
async def test_purchase_rejects_demand_listings(
    client: AsyncClient,
    started_app,
    auth_headers: dict[str, str],
    second_user_headers: dict[str, str],
) -> None:
    created = await create_listing(client, auth_headers, is_offer=False)
    container = started_app.state.container

    async with container.database.session() as session:
        buyer = await _user(session, "buyer2@example.com")
        with pytest.raises(BusinessRuleViolation):
            await orders_service.purchase(
                session,
                item_id=created["id"],
                buyer=buyer,
                settings=container.settings,
            )


@pytest.mark.asyncio
async def test_out_of_stock_error_code(
    client: AsyncClient,
    started_app,
    auth_headers: dict[str, str],
    second_user_headers: dict[str, str],
) -> None:
    created = await create_listing(client, auth_headers, inventory=0)
    container = started_app.state.container

    async with container.database.session() as session:
        buyer = await _user(session, "buyer2@example.com")
        with pytest.raises((OutOfStockError, BusinessRuleViolation)):
            await orders_service.purchase(
                session,
                item_id=created["id"],
                buyer=buyer,
                settings=container.settings,
            )
