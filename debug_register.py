import httpx
import asyncio

async def test_register():
    url = "http://127.0.0.1:8000/users/"
    data = {"username": "testuser_500", "email": "test_500@example.com", "password": "StrongPassword123", "age": 25, "phone": "1234567890"}
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=data)
            print(f"Status: {resp.status_code}")
            print(f"Response: {resp.text}")
        except Exception as e:
            print(f"Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_register())
