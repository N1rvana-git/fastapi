import pytest
from httpx import AsyncClient
from fastapi import HTTPException
from starlette import status

# 引入 app 和依赖，用于 health_check 的 mock 测试
from src.main import app
from src.posts.dependencies import get_db_session

# 注意：我们删除了这里所有关于数据库配置和 async_client 的代码
# 因为它们已经被干净地移到了 tests/conftest.py 里，pytest 会自动找到它们！

# --- 测试用例 ---

@pytest.mark.asyncio
async def test_read_root(async_client: AsyncClient):
    response = await async_client.get("/")
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["message"] == "Welcome to my practice"
    assert response_json["环境"] == "development"

@pytest.mark.asyncio
async def test_create_and_read_item(async_client: AsyncClient):
    """
    测试完整闭环：注册 -> 登录 -> 创建物品 -> 读取物品
    """
    # 1. 注册一个新用户
    register_response = await async_client.post(
        "/users/", 
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "ValidPassword123"
        }
    )
    assert register_response.status_code == 200

    # 2. 登录以获取 Token (注意：登录接口用的是 form-data 格式，所以用 data=)
    login_response = await async_client.post(
        "/token", 
        data={
            "username": "test@example.com", 
            "password": "ValidPassword123"
        }
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    
    # 3. 准备带有 Token 的请求头
    headers = {"Authorization": f"Bearer {token}"}

    # 4. 创建物品 (携带 Header！)
    test_item_json = {
        "name": "Test Item", 
        "price": 123.45, 
        "is_offer": False
    }
    response_post = await async_client.post(
        "/items/", 
        json=test_item_json,
        headers=headers  # <--- 关键：出示“身份证”
    )
    assert response_post.status_code == 200
    
    response_data = response_post.json()
    assert response_data["name"] == "Test Item"
    assert response_data["price"] == 123.45
    assert "id" in response_data       # 确保返回了 id
    assert "owner_id" in response_data # 确保绑定了主人

    # 5. 读取物品列表，验证是否写入成功
    response_get = await async_client.get("/items/")
    assert response_get.status_code == 200
    items_list = response_get.json()
    assert len(items_list) == 1
    assert items_list[0]["name"] == "Test Item"

@pytest.mark.asyncio
async def test_read_items_with_filter(async_client: AsyncClient):
    """
    测试读取过滤功能 (同样需要先登录才能创建初始数据)
    """
    # 1. 注册 & 登录拿 Token (快速流)
    await async_client.post("/users/", json={"username": "u1", "password": "Password123", "email": "u1@e.com"})
    token = (await async_client.post("/token", data={"username": "u1@e.com", "password": "Password123"})).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. 创建测试数据
    item_offer_json = {"name": "on offer", "price": 10.0, "is_offer": True}
    item_not_offer_json = {"name": "not on offer", "price": 10.0, "is_offer": False}

    await async_client.post("/items/", json=item_offer_json, headers=headers)
    await async_client.post("/items/", json=item_not_offer_json, headers=headers)

    # 3. 测试 is_offer_filter=True
    response_true = await async_client.get("/items/", params={"is_offer_filter": True})
    assert response_true.status_code == 200
    assert len(response_true.json()) == 1
    assert response_true.json()[0]["name"] == "on offer"

    # 4. 测试 is_offer_filter=False
    response_false = await async_client.get("/items/", params={"is_offer_filter": False})
    assert response_false.status_code == 200
    assert len(response_false.json()) == 1
    assert response_false.json()[0]["name"] == "not on offer"

    # 5. 测试不过滤
    response_all = await async_client.get("/items/")
    assert response_all.status_code == 200
    assert len(response_all.json()) == 2

@pytest.mark.asyncio
async def test_health_check_succeeds(async_client: AsyncClient):
    response = await async_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

@pytest.mark.asyncio
async def test_health_check_fails(async_client: AsyncClient, monkeypatch):
    async def mock_db_fail():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Mock DB Failure"
        )
    app.dependency_overrides[get_db_session] = mock_db_fail

    try:
        response = await async_client.get("/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"detail": "Mock DB Failure"}
    finally:
        app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_create_and_update_item(async_client: AsyncClient):
        # 1. 注册一个新用户
    register_response = await async_client.post(
        "/users/", 
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "ValidPassword123"
        }
    )
    assert register_response.status_code == 200

    # 2. 登录以获取 Token (注意：登录接口用的是 form-data 格式，所以用 data=)
    login_response = await async_client.post(
        "/token", 
        data={
            "username": "test@example.com", 
            "password": "ValidPassword123"
        }
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    
    # 3. 准备带有 Token 的请求头
    headers = {"Authorization": f"Bearer {token}"}

    # 4. 创建物品 (携带 Header！)
    test_item_json = {
        "name": "Test Item", 
        "price": 123.45, 
        "is_offer": False
    }
    response_post = await async_client.post(
        "/items/", 
        json=test_item_json,
        headers=headers  # <--- 关键：出示“身份证”
    )
    assert response_post.status_code == 200
    
    response_data = response_post.json()
    assert response_data["name"] == "Test Item"
    assert response_data["price"] == 123.45
    assert "id" in response_data       # 确保返回了 id
    assert "owner_id" in response_data # 确保绑定了主人

    # 5. 更新物品
    item_id = response_data["id"]
    response_put = await async_client.put(
        f"/items/{item_id}", 
        json={"price": 999.99}, 
        headers=headers
    )
    assert response_put.status_code == 200
    assert response_put.json()["price"] == 999.99

    item_id = response_data["id"]
    response_delete = await async_client.delete(
        f"/items/{item_id}", 
        headers=headers
    )
    assert response_delete.status_code == 204
    response_check_deleted = await async_client.get(f"/items/")
    assert len(response_check_deleted.json()) == 0

@pytest.mark.asyncio
async def test_create_and_update_item(async_client: AsyncClient):
        # 1. 注册一个新用户
    register_response = await async_client.post(
        "/users/", 
        json={
            "username": "testuser",
            "email": "test@example.com",
            "password": "ValidPassword123"
        }
    )
    assert register_response.status_code == 200

    # 2. 登录以获取 Token (注意：登录接口用的是 form-data 格式，所以用 data=)
    login_response = await async_client.post(
        "/token", 
        data={
            "username": "test@example.com", 
            "password": "ValidPassword123"
        }
    )
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    
    # 3. 准备带有 Token 的请求头
    headers = {"Authorization": f"Bearer {token}"}

    # 4. 创建物品 (携带 Header！)
    test_item_json = {
        "name": "Test Item", 
        "price": 123.45, 
        "is_offer": False
    }
    response_post = await async_client.post(
        "/items/", 
        json=test_item_json,
        headers=headers  # <--- 关键：出示“身份证”
    )
    assert response_post.status_code == 200
    
    response_data = response_post.json()
    assert response_data["name"] == "Test Item"
    assert response_data["price"] == 123.45
    assert "id" in response_data       # 确保返回了 id
    assert "owner_id" in response_data # 确保绑定了主人

    # 5.造标签
    item_tags_response = await async_client.post(
        "/items/tags/",
        json={"name": "TestTag1"},
        headers=headers
    )
    assert item_tags_response.status_code == 200
    tag_data = item_tags_response.json()
    assert tag_data["name"] == "TestTag1"
    
    tags_new_id = tag_data["id"]

    # 6.给物品加上标签
    reponse_put_tags = await async_client.put(
        f"/items/{response_data['id']}",
        json={
            "price": 888.88,
            "tag_ids": [tags_new_id]
            },
        headers=headers
    )
    assert reponse_put_tags.status_code == 200
    
    # 7. 验证标签是否成功关联
    updated_item_data = reponse_put_tags.json()
    assert "tags" in updated_item_data
    assert len(updated_item_data["tags"]) == 1
    assert updated_item_data["tags"][0]["name"] == "TestTag1"