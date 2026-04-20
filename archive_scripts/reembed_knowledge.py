import asyncio
from sqlalchemy import select
from src.database import AsyncSessionLocal
from src.posts.models import KnowledgeModel
from zhipuai import ZhipuAI
from src.config import settings

async def main():
    ai_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
    async with AsyncSessionLocal() as db:
        try:
            chunks = (await db.execute(select(KnowledgeModel))).scalars().all()
            for chunk in chunks:
                print(f"Re-embedding Knowledge: {chunk.title}")
                res = ai_client.embeddings.create(model="embedding-2", input=chunk.content)
                chunk.embedding = res.data[0].embedding
            await db.commit()
            print("Knowledge Re-embed complete!")
        except Exception as e:
            print("No knowledge base found or re-embed failed", e)

if __name__ == "__main__":
    asyncio.run(main())
