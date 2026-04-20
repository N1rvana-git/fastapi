import asyncio
from src.database import AsyncSessionLocal
from sqlalchemy import text

async def main():
    async with AsyncSessionLocal() as session:
        await session.execute(text('ALTER TABLE item ALTER COLUMN embedding TYPE vector(1536);'))
        await session.commit()
        print("PGVector dimension updated to 1536.")

if __name__ == "__main__":
    asyncio.run(main())
