"""Health probes and response hardening."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_liveness_never_touches_dependencies(client: AsyncClient) -> None:
    response = await client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["uptime_seconds"] >= 0


@pytest.mark.asyncio
async def test_legacy_health_endpoint_still_works(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readiness_reports_checks(client: AsyncClient) -> None:
    response = await client.get("/health/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    checks = {check["name"]: check for check in body["checks"]}
    assert checks["database"]["ok"] is True
    # The LLM is optional for serving traffic; its absence is reported but does
    # not fail readiness.
    assert checks["llm"]["ok"] is False
    assert body["status"] == "ok"


@pytest.mark.asyncio
async def test_trace_id_is_propagated_and_generated(client: AsyncClient) -> None:
    provided = await client.get("/health/live", headers={"X-Trace-ID": "trace-abc-123456"})
    assert provided.headers["X-Trace-ID"] == "trace-abc-123456"

    generated = await client.get("/health/live")
    assert len(generated.headers["X-Trace-ID"]) >= 8
    assert generated.headers["X-Request-ID"] == generated.headers["X-Trace-ID"]


@pytest.mark.asyncio
async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_body_size_limit(app, settings) -> None:
    from httpx import ASGITransport

    small_limit_app = __import__("src.app.main", fromlist=["create_app"]).create_app(
        settings.model_copy(update={"MAX_REQUEST_BYTES": 64})
    )
    async with small_limit_app.router.lifespan_context(small_limit_app):
        transport = ASGITransport(app=small_limit_app)
        async with AsyncClient(transport=transport, base_url="http://test") as http_client:
            response = await http_client.post(
                "/users/register", json={"email": "big@example.com", "password": "x" * 200}
            )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
