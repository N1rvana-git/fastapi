import asyncio
from src.database import AsyncSessionLocal
from sqlalchemy import text

async def test():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT 1"))
        print(res.scalar())

asyncio.run(test())
