import asyncio
from zhipuai import ZhipuAI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update
from src.posts.models import ItemModel
from src.config import settings

ai_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)

async def main():
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        # Find items with NULL embeddings
        query = select(ItemModel).where(ItemModel.embedding.is_(None))
        result = await session.execute(query)
        items = result.scalars().all()
        
        for item in items:
            print(f"Fixing embedding for ID {item.id} - {item.name}")
            try:
                response = ai_client.embeddings.create(
                    model="embedding-2",
                    input=item.name
                )
                vector = response.data[0].embedding
                item.embedding = vector
                session.add(item)
                print(f"Success for {item.name}")
            except Exception as e:
                print(f"Failed for {item.name}: {e}")
        
        await session.commit()
        print(f"Fixed {len(items)} items!")

if __name__ == "__main__":
    asyncio.run(main())
