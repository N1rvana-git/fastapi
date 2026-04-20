import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        print('Altering item.embedding -> vector(1024) using slice')
        await db.execute(text("ALTER TABLE item ALTER COLUMN embedding TYPE vector(1024) USING embedding[1:1024]"))
        try:
            print('Altering knowledge_base.embedding -> vector(1024) using slice')
            await db.execute(text("ALTER TABLE knowledge_base ALTER COLUMN embedding TYPE vector(1024) USING embedding[1:1024]"))
        except Exception as e:
            print('knowledge_base alter skipped or failed:', e)
        await db.commit()
        print('Alter with USING complete')

if __name__ == '__main__':
    asyncio.run(main())
