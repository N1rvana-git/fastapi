import asyncio
from src.database import AsyncSessionLocal
from src.posts.models import ItemModel
from sqlalchemy import select

async def main():
    async with AsyncSessionLocal() as db:
        item_id_int = 28
        try:
            q = select(ItemModel).where(ItemModel.id == item_id_int)
            await db.execute(q)
            print("int OK")
        except Exception as e:
            print("int FAIL:", type(e).__name__)

    async with AsyncSessionLocal() as db:
        item_id_str = "28"
        try:
            q = select(ItemModel).where(ItemModel.id == item_id_str)
            await db.execute(q)
            print("string OK")
        except Exception as e:
            print("string FAIL:", type(e).__name__)

asyncio.run(main())
