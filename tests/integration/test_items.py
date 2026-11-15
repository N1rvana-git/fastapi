"""Listing CRUD, tags, favourites, media and search."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from tests.conftest import create_listing

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.mark.asyncio
async def test_create_and_read_listing(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await create_listing(client, auth_headers)
    assert created["name"] == "九成新机械键盘"
    assert created["inventory"] == 1
    assert created["is_sold"] is False
    assert created["owner_id"] is not None

    listing = await client.get("/items")
    assert listing.status_code == 200
    body = listing.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]
    assert "embedding" not in body["items"][0]

    single = await client.get(f"/items/{created['id']}")
    assert single.status_code == 200


@pytest.mark.asyncio
async def test_validation_is_strict(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    negative = await client.post("/items", json={"name": "x", "price": -1}, headers=auth_headers)
    assert negative.status_code == 422
    assert negative.json()["error"]["code"] == "VALIDATION_ERROR"

    unknown_field = await client.post(
        "/items", json={"name": "x", "price": 1, "surprise": True}, headers=auth_headers
    )
    assert unknown_field.status_code == 422


@pytest.mark.asyncio
async def test_create_requires_authentication(client: AsyncClient) -> None:
    response = await client.post("/items", json={"name": "x", "price": 1})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_update_and_delete_respect_ownership(
    client: AsyncClient, auth_headers: dict[str, str], second_user_headers: dict[str, str]
) -> None:
    created = await create_listing(client, auth_headers)

    forbidden = await client.put(
        f"/items/{created['id']}", json={"price": 1.0}, headers=second_user_headers
    )
    assert forbidden.status_code == 403

    updated = await client.put(
        f"/items/{created['id']}", json={"price": 199.0}, headers=auth_headers
    )
    assert updated.status_code == 200
    assert updated.json()["price"] == 199.0

    deleted = await client.delete(f"/items/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 204
    assert (await client.get(f"/items/{created['id']}")).status_code == 404


@pytest.mark.asyncio
async def test_pagination_and_filters(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    for index in range(3):
        await create_listing(client, auth_headers, name=f"商品{index}", is_offer=index % 2 == 0)

    page = await client.get("/items", params={"limit": 2, "skip": 0})
    body = page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2

    offers = await client.get("/items", params={"is_offer_filter": True})
    assert offers.json()["total"] == 2

    searched = await client.get("/items", params={"search": "商品1"})
    assert searched.json()["total"] == 1


@pytest.mark.asyncio
async def test_idempotent_create_replays_the_same_listing(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    headers = {**auth_headers, "X-Idempotency-Key": "create-42"}
    payload = {"name": "限量球鞋", "price": 888.0}

    first = await client.post("/items", json=payload, headers=headers)
    second = await client.post("/items", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.headers.get("X-Idempotent-Replay") == "true"

    listing = await client.get("/items")
    assert listing.json()["total"] == 1


@pytest.mark.asyncio
async def test_same_idempotency_key_with_different_payload_conflicts(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    headers = {**auth_headers, "X-Idempotency-Key": "create-43"}
    await client.post("/items", json={"name": "A", "price": 1.0}, headers=headers)
    conflicting = await client.post("/items", json={"name": "B", "price": 2.0}, headers=headers)
    assert conflicting.status_code == 409


@pytest.mark.asyncio
async def test_tags_crud_and_cache_invalidation(
    client: AsyncClient,
    auth_headers: dict[str, str],
    admin_headers: dict[str, str],
) -> None:
    assert (await client.get("/items/tags")).json() == []

    created = await client.post("/items/tags", json={"name": "数码"}, headers=auth_headers)
    assert created.status_code == 201
    assert (await client.get("/items/tags")).json() == [
        {"id": created.json()["id"], "name": "数码"}
    ]

    duplicate = await client.post("/items/tags", json={"name": "数码"}, headers=auth_headers)
    assert duplicate.status_code == 422

    forbidden = await client.delete(f"/items/tags/{created.json()['id']}", headers=auth_headers)
    assert forbidden.status_code == 403

    removed = await client.delete(f"/items/tags/{created.json()['id']}", headers=admin_headers)
    assert removed.status_code == 204
    assert (await client.get("/items/tags")).json() == []


@pytest.mark.asyncio
async def test_listing_with_tags(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    tag = await client.post("/items/tags", json={"name": "键盘"}, headers=auth_headers)
    created = await create_listing(client, auth_headers, tag_ids=[tag.json()["id"]])
    assert created["tags"][0]["name"] == "键盘"

    missing = await client.post(
        "/items", json={"name": "x", "price": 1, "tag_ids": [9999]}, headers=auth_headers
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["details"]["missing_tag_ids"] == [9999]


@pytest.mark.asyncio
async def test_favourite_toggle(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    created = await create_listing(client, auth_headers)
    first = await client.post(f"/items/{created['id']}/favorite", headers=auth_headers)
    assert first.status_code == 200
    assert first.json() == {"message": "收藏成功", "favorited": True, "favourited_count": 1}

    second = await client.post(f"/items/{created['id']}/favorite", headers=auth_headers)
    assert second.json()["favorited"] is False
    assert second.json()["favourited_count"] == 0


@pytest.mark.asyncio
async def test_image_upload_uses_generated_filename(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/items/upload-image",
        files={"file": ("../../evil.png", PNG_BYTES, "image/png")},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["url"].startswith("/uploads/items/")
    assert "evil" not in body["url"]
    assert body["image_embedding"] is None  # vision disabled in tests


@pytest.mark.asyncio
async def test_upload_rejects_bad_extension_and_mismatched_content(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    bad_extension = await client.post(
        "/items/upload-image",
        files={"file": ("payload.exe", b"MZ", "application/octet-stream")},
        headers=auth_headers,
    )
    assert bad_extension.status_code == 400

    fake_png = await client.post(
        "/items/upload-image",
        files={"file": ("photo.png", b"not-an-image", "image/png")},
        headers=auth_headers,
    )
    assert fake_png.status_code == 400


@pytest.mark.asyncio
async def test_text_search_falls_back_to_lexical(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    await create_listing(client, auth_headers, name="罗技机械键盘")
    await create_listing(client, auth_headers, name="冬季羽绒服")

    response = await client.post("/items/search-by-text", json={"query_text": "键盘"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "lexical"
    assert [item["name"] for item in body["data"]] == ["罗技机械键盘"]
    assert body["data"][0]["match_reason"] == "lexical"


@pytest.mark.asyncio
async def test_image_search_reports_feature_unavailable(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/items/search-by-image", files={"file": ("q.png", PNG_BYTES, "image/png")}
    )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "FEATURE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_dashboard_aggregates_user_data(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    created = await create_listing(client, auth_headers)
    response = await client.get("/items/dashboard/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["stats"]["published_count"] == 1
    assert body["stats"]["orders_count"] == 0
    assert body["my_items"][0]["id"] == created["id"]
