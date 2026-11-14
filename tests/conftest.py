"""Test configuration.

Everything the application reads at import time is pinned here *before* the
first ``src.app`` import: tests run against an isolated in-memory SQLite
database, with Redis unavailable (degraded, in-memory adapters) and without any
upstream API keys, so no test can ever reach a paid service.
"""

from __future__ import annotations

import os

_TEST_UPLOAD_DIR = os.path.join(os.environ.get("TEMP", "/tmp"), "xianxiaobao-test-uploads")

os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        "REDIS_URL": "redis://127.0.0.1:6399/15",
        "REDIS_SOCKET_TIMEOUT": "0.1",
        "SECRET_KEY": "test-secret-key-that-is-long-enough-32chars",
        "CHAT_API_KEY": "",
        "API_KEY": "",
        "API_KEy": "",
        "ZHIPUAI_API_KEY": "",
        "TASKS_EAGER": "true",
        "TASKS_ENABLED": "true",
        "EMBEDDING_ENABLED": "false",
        "VISION_ENABLED": "false",
        "LOG_LEVEL": "WARNING",
        "LOG_FORMAT": "json",
        "RATE_LIMIT_ENABLED": "true",
        "FEISHU_APP_ID": "",
        "FEISHU_APP_SECRET": "",
        "FEISHU_VERIFICATION_TOKEN": "test-verification-token",
        "UPLOAD_DIR": _TEST_UPLOAD_DIR,
    }
)

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from src.app.core.config import get_settings  # noqa: E402
from src.app.core.database import Base  # noqa: E402
from src.app.main import create_app  # noqa: E402
from src.app.modules.chat.service import ChatDeps, ChatService  # noqa: E402
from src.app.modules.chat.stream_runtime import AgentEvent  # noqa: E402
from src.app.shared.deps import get_chat_service  # noqa: E402

# Fail fast if a real key leaks into the test environment.
assert get_settings().chat_api_key == "", "tests must not have an LLM API key configured"


class FakeAgentRuntime:
    """Deterministic runtime: text only, or an approval interrupt on demand."""

    def __init__(self, *, tokens: list[str] | None = None, interrupt: dict | None = None) -> None:
        self.tokens = tokens or ["你好", "，", "我是闲小宝"]
        self.interrupt = interrupt
        self.calls = 0

    async def run(self, *, user_id, user_name, thread_id, messages, cancel_event):
        self.calls += 1
        for token in self.tokens:
            if cancel_event.is_set():
                yield AgentEvent("aborted", {"reason": "client_disconnected"})
                return
            yield AgentEvent("token", {"text": token})
        if self.interrupt is not None:
            yield AgentEvent("interrupt_required", self.interrupt)
        yield AgentEvent("done", {"steps": 1})


@pytest.fixture()
def settings():
    return get_settings()


@pytest.fixture()
def app(settings) -> FastAPI:
    return create_app(settings)


@pytest_asyncio.fixture()
async def started_app(app: FastAPI) -> AsyncIterator[FastAPI]:
    async with app.router.lifespan_context(app):
        async with app.state.container.database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture()
async def client(started_app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=started_app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client


@pytest_asyncio.fixture()
async def fake_runtime(started_app: FastAPI) -> FakeAgentRuntime:
    """Override the real runtime so no test needs an LLM."""

    runtime = FakeAgentRuntime()
    container = started_app.state.container
    service = ChatService(
        deps=ChatDeps(
            settings=container.settings,
            database=container.database,
            runtime=runtime,
            buffer=container.stream_buffer,
            locks=container.locks,
            idempotency=container.idempotency,
        )
    )
    started_app.dependency_overrides[get_chat_service] = lambda: service
    return runtime


async def register_and_login(
    client: AsyncClient,
    *,
    email: str = "user@example.com",
    password: str = "Password123",
) -> dict[str, str]:
    response = await client.post("/users/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    token_response = await client.post("/token", data={"username": email, "password": password})
    assert token_response.status_code == 200, token_response.text
    return {"Authorization": f"Bearer {token_response.json()['access_token']}"}


@pytest_asyncio.fixture()
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    return await register_and_login(client)


@pytest_asyncio.fixture()
async def second_user_headers(client: AsyncClient) -> dict[str, str]:
    return await register_and_login(client, email="buyer2@example.com")


@pytest_asyncio.fixture()
async def admin_headers(client: AsyncClient, started_app: FastAPI) -> dict[str, str]:
    """Register an account, then promote it in the database.

    Tokens carry no authority: ``get_current_user`` re-reads the role from the
    database on every request, so promoting the row is enough.
    """

    from src.app.modules.users import repository as users_repository

    headers = await register_and_login(client, email="admin@example.com")
    async with started_app.state.container.database.session() as session:
        user = await users_repository.get_by_email(session, "admin@example.com")
        assert user is not None
        user.role = "admin"
        await session.commit()
    return headers


async def create_listing(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "九成新机械键盘",
    price: float = 299.0,
    inventory: int = 1,
    **extra: object,
) -> dict:
    payload = {"name": name, "price": price, "inventory": inventory, **extra}
    response = await client.post("/items", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()
