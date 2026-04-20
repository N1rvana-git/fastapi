import asyncio
from sqlalchemy import text
from src.database import AsyncSessionLocal

async def main():
    async with AsyncSessionLocal() as db:
        for table in ['item','knowledge_base']:
            try:
                res = await db.execute(text("SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod) as coltype FROM pg_attribute a JOIN pg_class c ON a.attrelid=c.oid WHERE c.relname=:table AND a.attname='embedding' AND a.attnum>0 AND NOT a.attisdropped"), {'table': table})
                rows = res.fetchall()
                print(table, rows)
            except Exception as e:
                print('error', table, e)

        # 查找公共 schema 下所有名为 embedding 的列
        res = await db.execute(text("SELECT c.relname AS table, a.attname AS column, pg_catalog.format_type(a.atttypid,a.atttypmod) AS coltype FROM pg_attribute a JOIN pg_class c ON a.attrelid=c.oid JOIN pg_namespace n ON c.relnamespace=n.oid WHERE a.attnum>0 AND NOT a.attisdropped AND a.attname='embedding' AND n.nspname='public'"))
        rows = res.fetchall()
        print('\nAll embedding columns:')
        for r in rows:
            print(r)

if __name__ == '__main__':
    asyncio.run(main())
