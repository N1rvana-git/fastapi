import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod) as coltype FROM pg_attribute a JOIN pg_class c ON a.attrelid=c.oid WHERE c.relname='item' AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum"))
        rows = res.fetchall()
        print('item columns:')
        for r in rows:
            print(r)

if __name__ == '__main__':
    asyncio.run(main())
