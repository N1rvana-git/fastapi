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
            print(f"Re-embedding -> item_embedding table: {search_query}")
            res = ai_client.embeddings.create(model="embedding-2", input=search_query)
            emb = res.data[0].embedding
            emb_str = '[' + ','.join(str(x) for x in emb) + ']'
            await db.execute(text("INSERT INTO item_embedding (item_id, embedding) VALUES (:id, CAST(:emb AS vector(1024))) ON CONFLICT (item_id) DO UPDATE SET embedding = EXCLUDED.embedding"), {"id": item.id, "emb": emb_str})
        await db.commit()
        print("Re-embed into item_embedding complete!")

if __name__ == '__main__':
    asyncio.run(main())
