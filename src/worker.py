import time
import asyncio
from celery import Celery
from zhipuai import ZhipuAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 🌟 导入你项目里的数据库组件 (根据你的实际文件名调整，比如 src.database)
from src.database import engine 
from src.posts.models import ItemModel

celery_app = Celery(
    "idle_platform_worker",
    broker="redis://redis:6379/0",
    backend="redis://redis:6379/1"
)

# 🌟 初始化 AI 大脑（填入你的真实 Key）
ai_client = ZhipuAI(api_key="b40d93bc3d5748dd9fd47efdc32d0f0c.nhsV68wYizfmYx6v")

@celery_app.task
def inject_embedding_task(item_id: int, item_name: str):
    print(f"🧠 [黑灯工厂] 正在为商品【{item_name}】锻造 1024 维高维灵魂...")
    
    try:
        # 1. 极其耗时的操作：向智谱发起网络请求，获取向量
        embed_response = ai_client.embeddings.create(
            model="embedding-2",
            input=item_name
        )
        vector = embed_response.data[0].embedding
        print(f"✨ [黑灯工厂] 向量提取成功，准备打入数据库...")

        # 2. Celery 是同步环境，我们需要用 asyncio 来跑异步的 SQLAlchemy
        async def update_db():
            # 开启一个临时的数据库通道
            async with AsyncSession(engine) as session:
                item = await session.get(ItemModel, item_id)
                if item:
                    item.embedding = vector
                    await session.commit()
                    print(f"✅ [黑灯工厂] 灵魂物理固化成功！商品 ID: {item_id}")
                    
        asyncio.run(update_db())
        return f"Success: {item_name} embedding injected."
        
    except Exception as e:
        print(f"⚠️ [黑灯工厂] 锻造失败: {e}")
        return f"Failed: {e}"