import asyncio
from sqlalchemy import select
from src.database import AsyncSessionLocal
from src.posts.models import ItemModel, KnowledgeModel
from openai import AsyncOpenAI
from src.config import settings

async def main():
    async_chat_client = AsyncOpenAI(api_key=settings.API_KEy or settings.API_KEY, base_url="https://api.zetatechs.com/v1")
    
    async with AsyncSessionLocal() as db:
        # 1. Re-embed items
        items = (await db.execute(select(ItemModel))).scalars().all()
        for item in items:
            search_query = f"{item.name} {getattr(item, 'description', '')}"
            print(f"Re-embedding Item: {search_query}")
            try:
                res = await async_chat_client.embeddings.create(model="text-embedding-004", input=search_query)
                item.embedding = res.data[0].embedding
            except Exception as e:
                print(f"Error Item: {e}")
        
        # 2. Re-embed knowledge_base
        try:
            chunks = (await db.execute(select(KnowledgeModel))).scalars().all()
            for chunk in chunks:
                print(f"Re-embedding Knowledge: {chunk.title}")
                res = await async_chat_client.embeddings.create(model="text-embedding-004", input=chunk.content)
                chunk.embedding = res.data[0].embedding
        except Exception as e:
            print("Knowledge base re-embed bypassed:", e)

        await db.commit()
        print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
