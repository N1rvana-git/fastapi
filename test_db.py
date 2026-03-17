import asyncio
from src.database import async_session_maker
from src.posts.models import ItemModel
from sqlalchemy import select

async def main():
    async with async_session_maker() as db:
        item_id = 28
        price_query = select(ItemModel).where(ItemModel.id == item_id).where(ItemModel.is_offer == True).where(ItemModel.is_sold == False)
        print(price_query.compile(compile_kwargs={"literal_binds": True}))
        try:
            res = await db.execute(price_query)
            print(res.scalars().first())
        except Exception as e:
            print("ERROR", str(e))

asyncio.run(main())
