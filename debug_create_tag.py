import httpx
import asyncio

async def test_create_tag():
    base_url = "http://127.0.0.1:8000"
    
    # 1. Login to get token
    login_data = {
        "username": "test_500@example.com",
        "password": "StrongPassword123"
    }
    
    async with httpx.AsyncClient() as client:
        print("Logging in...")
        try:
            login_resp = await client.post(f"{base_url}/token", data=login_data)
            if login_resp.status_code != 200:
                print(f"Login failed: {login_resp.status_code} - {login_resp.text}")
                return
            
            token_data = login_resp.json()
            access_token = token_data["access_token"]
            print(f"Login success! Token: {access_token[:10]}...")
            
            # 2. Create Tag
            headers = {"Authorization": f"Bearer {access_token}"}
            tag_data = {"name": "TestTag1"}
            
            print("Creating tag...")
            tag_resp = await client.post(f"{base_url}/items/tags/", json=tag_data, headers=headers)
            
            print(f"Create Tag Status: {tag_resp.status_code}")
            print(f"Create Tag Response: {tag_resp.text}")

        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_create_tag())
