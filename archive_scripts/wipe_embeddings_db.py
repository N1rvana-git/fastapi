import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal
import asyncpg

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(text("UPDATE item SET embedding = NULL"))
        await db.execute(text("ALTER TABLE item ALTER COLUMN embedding TYPE vector(1536)"))
        try:
            await db.execute(text("UPDATE knowledge_base SET embedding = NULL"))
            await db.execute(text("ALTER TABLE knowledge_base ALTER COLUMN embedding TYPE vector(1536)"))
        except Exception as e:
            print("knowledge_base not found, skipping.", e)
        await db.commit()
        print("Database schema and embeddings reset.")

if __name__ == "__main__":
    asyncio.run(main())
