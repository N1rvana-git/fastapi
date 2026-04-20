import asyncio
from sqlalchemy import select
from src.database import AsyncSessionLocal
from src.posts.models import ItemModel
from openai import AsyncOpenAI
from src.config import settings

async def main():
    async_chat_client = AsyncOpenAI(api_key=settings.API_KEy or settings.API_KEY, base_url="https://api.zetatechs.com/v1")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ItemModel))
        items = result.scalars().all()
        
        for item in items:
            search_query = f"{item.name}"
            print(f"Re-embedding: {search_query}...")
            embed_response = await async_chat_client.embeddings.create(model="text-embedding-3-small", input=search_query)
            item.embedding = embed_response.data[0].embedding
            await db.commit()
            print(f"✅ Item {item.id} embedded successfully.")

if __name__ == "__main__":
    asyncio.run(main())
