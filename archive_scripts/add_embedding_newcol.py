import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(text("ALTER TABLE item ADD COLUMN IF NOT EXISTS embedding_1024 vector(1024)"))
        try:
            await db.execute(text("ALTER TABLE knowledge_base ADD COLUMN IF NOT EXISTS embedding_1024 vector(1024)"))
        except Exception:
            pass
        await db.commit()
        print('Added embedding_1024 columns (if not exists)')

if __name__ == '__main__':
    asyncio.run(main())
