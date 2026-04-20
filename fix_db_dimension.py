import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(text("ALTER TABLE item ALTER COLUMN embedding TYPE vector(1024)"))
        try:
            await db.execute(text("ALTER TABLE knowledge_base ALTER COLUMN embedding TYPE vector(1024)"))
        except:
            pass
        await db.commit()
        print("Database schema reset to 1024.")

if __name__ == "__main__":
    asyncio.run(main())
