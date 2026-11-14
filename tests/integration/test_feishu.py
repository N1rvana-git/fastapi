"""Feishu webhook and account binding."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

VERIFICATION_TOKEN = "test-verification-token"


@pytest.mark.asyncio
async def test_url_verification_challenge(client: AsyncClient) -> None:
    response = await client.post(
        "/feishu/webhook", json={"type": "url_verification", "challenge": "abc"}
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "abc"}


@pytest.mark.asyncio
async def test_invalid_verification_token_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/feishu/webhook",
        json={
            "token": "wrong",
            "header": {"event_type": "im.message.receive_v1"},
            "event": {},
        },
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_message_event_is_acknowledged_fast(client: AsyncClient) -> None:
    response = await client.post(
        "/feishu/webhook",
        json={
            "token": VERIFICATION_TOKEN,
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_unbound"}},
                "message": {"message_type": "text", "content": '{"text":"你好"}'},
            },
        },
    )
    assert response.status_code == 200
    assert response.json() == {"msg": "ok"}


@pytest.mark.asyncio
async def test_unsupported_event_type_is_ignored(client: AsyncClient) -> None:
    response = await client.post(
        "/feishu/webhook",
        json={"token": VERIFICATION_TOKEN, "header": {"event_type": "im.chat.updated"}},
    )
    assert response.status_code == 200
    assert response.json() == {"msg": "ignored"}


@pytest.mark.asyncio
async def test_bind_account_and_reject_duplicates(
    client: AsyncClient,
    auth_headers: dict[str, str],
    second_user_headers: dict[str, str],
) -> None:
    first = await client.post("/feishu/bind", json={"open_id": "ou_123"}, headers=auth_headers)
    assert first.status_code == 200

    duplicate = await client.post(
        "/feishu/bind", json={"open_id": "ou_123"}, headers=second_user_headers
    )
    assert duplicate.status_code == 409

    me = await client.get("/auth/me", headers=auth_headers)
    assert me.status_code == 200


@pytest.mark.asyncio
async def test_duplicate_event_is_processed_once(
    client: AsyncClient, started_app, auth_headers: dict[str, str]
) -> None:
    """Feishu retries the webhook; message_id makes processing idempotent."""

    import asyncio

    await client.post("/feishu/bind", json={"open_id": "ou_dup"}, headers=auth_headers)
    payload = {
        "token": VERIFICATION_TOKEN,
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "sender": {"sender_id": {"open_id": "ou_dup"}},
            "message": {
                "message_id": "om_same_event",
                "message_type": "text",
                "content": '{"text":"重复事件只处理一次"}',
            },
        },
    }
    first = await client.post("/feishu/webhook", json=payload)
    second = await client.post("/feishu/webhook", json=payload)
    assert first.status_code == 200 and second.status_code == 200

    for _ in range(100):
        history = await client.get(
            "/items/ai/history", params={"thread_id": "u1:feishu"}, headers=auth_headers
        )
        if len(history.json()) >= 2:
            break
        await asyncio.sleep(0.02)
    # user + assistant, exactly once despite two deliveries
    assert len(history.json()) == 2


@pytest.mark.asyncio
async def test_bound_user_message_writes_chat_history(
    client: AsyncClient, started_app, auth_headers: dict[str, str]
) -> None:
    await client.post("/feishu/bind", json={"open_id": "ou_bound"}, headers=auth_headers)

    response = await client.post(
        "/feishu/webhook",
        json={
            "token": VERIFICATION_TOKEN,
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "sender": {"sender_id": {"open_id": "ou_bound"}},
                "message": {"message_type": "text", "content": '{"text":"平台怎么退货？"}'},
            },
        },
    )
    assert response.status_code == 200

    # The eager dispatcher runs the task in-process; give it a moment to finish.
    import asyncio

    for _ in range(50):
        history = await client.get(
            "/items/ai/history", params={"thread_id": "u1:feishu"}, headers=auth_headers
        )
        if len(history.json()) >= 1:
            break
        await asyncio.sleep(0.02)
    assert history.json()[0]["role"] == "user"
