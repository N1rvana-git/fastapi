import asyncio
from sqlalchemy import select, text
from src.database import AsyncSessionLocal
from src.posts.models import ItemModel
from zhipuai import ZhipuAI
from src.config import settings

async def main():
    ai_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY or "")
    async with AsyncSessionLocal() as db:
        items = (await db.execute(select(ItemModel))).scalars().all()
        for item in items:
            search_query = f"{item.name} {getattr(item, 'description', '')}"
            print(f"Re-embedding -> embedding_1024: {search_query}")
            res = ai_client.embeddings.create(model="embedding-2", input=search_query)
            emb = res.data[0].embedding
            # update new column embedding_1024
            await db.execute(text("UPDATE item SET embedding_1024 = :emb WHERE id = :id"), {"emb": emb, "id": item.id})
        await db.commit()
        print("Re-embed to embedding_1024 complete!")

if __name__ == '__main__':
    asyncio.run(main())
