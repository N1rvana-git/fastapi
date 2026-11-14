"""Encrypted / signed Feishu webhook at the HTTP boundary."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from src.app.core.database import Base
from src.app.main import create_app
from tests.unit.test_feishu_security import KEY, encrypt_payload, sign

TOKEN = "test-verification-token"


@pytest_asyncio.fixture()
async def secure_client(settings) -> AsyncIterator[AsyncClient]:
    app = create_app(settings.model_copy(update={"FEISHU_ENCRYPT_KEY": KEY}))
    async with app.router.lifespan_context(app):
        async with app.state.container.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def _headers(timestamp: str, nonce: str, body: bytes) -> dict[str, str]:
    return {
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": sign(timestamp, nonce, body),
        "Content-Type": "application/json",
    }


@pytest.mark.asyncio
async def test_unsigned_request_is_rejected(secure_client: AsyncClient) -> None:
    response = await secure_client.post(
        "/feishu/webhook",
        json={"token": TOKEN, "header": {"event_type": "im.chat.updated"}},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_signed_plaintext_event_is_accepted(secure_client: AsyncClient) -> None:
    body = json.dumps({"token": TOKEN, "header": {"event_type": "im.chat.updated"}}).encode()
    timestamp = str(int(time.time()))
    response = await secure_client.post(
        "/feishu/webhook", content=body, headers=_headers(timestamp, "nonce-1", body)
    )
    assert response.status_code == 200
    assert response.json() == {"msg": "ignored"}


@pytest.mark.asyncio
async def test_signed_encrypted_challenge_is_decrypted(secure_client: AsyncClient) -> None:
    encrypted_body = json.dumps(
        {
            "encrypt": encrypt_payload(
                {"type": "url_verification", "challenge": "ch-encrypted", "token": TOKEN}
            )
        }
    ).encode()
    timestamp = str(int(time.time()))
    response = await secure_client.post(
        "/feishu/webhook",
        content=encrypted_body,
        headers=_headers(timestamp, "nonce-2", encrypted_body),
    )
    assert response.status_code == 200
    assert response.json() == {"challenge": "ch-encrypted"}


@pytest.mark.asyncio
async def test_stale_signature_is_rejected(secure_client: AsyncClient) -> None:
    body = json.dumps({"token": TOKEN}).encode()
    timestamp = str(int(time.time()) - 3600)
    response = await secure_client.post(
        "/feishu/webhook", content=body, headers=_headers(timestamp, "nonce-3", body)
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tampered_body_is_rejected(secure_client: AsyncClient) -> None:
    body = json.dumps({"token": TOKEN}).encode()
    timestamp = str(int(time.time()))
    headers = _headers(timestamp, "nonce-4", body)
    response = await secure_client.post(
        "/feishu/webhook", content=b'{"token":"other"}', headers=headers
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_encrypted_body_without_key_is_rejected(client: AsyncClient) -> None:
    # Default app: no FEISHU_ENCRYPT_KEY configured.
    body = json.dumps({"encrypt": encrypt_payload({})}).encode()
    response = await client.post("/feishu/webhook", content=body)
    assert response.status_code == 403
