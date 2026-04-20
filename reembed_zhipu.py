import asyncio
from sqlalchemy import select
from src.database import AsyncSessionLocal
from src.posts.models import ItemModel
from zhipuai import ZhipuAI
from src.config import settings

async def main():
    ai_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
    async with AsyncSessionLocal() as db:
        items = (await db.execute(select(ItemModel))).scalars().all()
        for item in items:
            search_query = f"{item.name} {getattr(item, 'description', '')}"
            print(f"Re-embedding: {search_query}")
            res = ai_client.embeddings.create(model="embedding-2", input=search_query)
            item.embedding = res.data[0].embedding
        await db.commit()
        print("Re-embed complete!")

if __name__ == "__main__":
    asyncio.run(main())
