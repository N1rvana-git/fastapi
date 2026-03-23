"""测试 PostgreSQL 连接并创建表"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from src.database import Base
from src.posts import models  # 导入所有模型
from src.config import settings

async def init_db():
    print(f"连接到数据库: {settings.DATABASE_URL}")
    
    engine = create_async_engine(settings.DATABASE_URL, echo=True)
    
    async with engine.begin() as conn:
        # 删除所有表（慎用！）
        # await conn.run_sync(Base.metadata.drop_all)
        
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        print("\n✅ 所有表创建成功！")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(init_db())
