import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import update
from src.posts.models import ItemModel
from src.config import settings

async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # 🌟 核心清理：把所有 is_sold 为 True 的旧商品的库存，全部抹零！
        query = update(ItemModel).where(ItemModel.is_sold == True).values(inventory=0)
        await session.execute(query)
        await session.commit()
        print("🎉 脏数据清洗完毕！所有售罄商品的库存已归零！")

if __name__ == "__main__":
    asyncio.run(main())