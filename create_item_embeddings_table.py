import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        await db.execute(text("CREATE TABLE IF NOT EXISTS item_embedding (item_id integer PRIMARY KEY, embedding vector(1024))"))
        await db.commit()
        print('Created table item_embedding (if not exists)')

if __name__ == '__main__':
    asyncio.run(main())
