import time
import asyncio
import requests
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
    
@celery_app.task
def send_feishu_alert_task(item_name: str, price: float, buyer_email: str, address: str):
    """
    触发企业级飞书卡片告警
    """
    print(f"🔔 [黑灯工厂] 检测到新订单！正在向飞书总部发送加密卡片...")
    
    # 🚨 把这里换成你刚刚在飞书群里复制的 Webhook URL ！！！
    webhook_url = "https://open.feishu.cn/open-apis/bot/v2/hook/c9032b83-2f3b-4a22-ac68-4623a48b16fe"
    
    # 🌟 核心魔法：极其骚气的飞书交互式卡片 JSON 结构
    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": "🚨 【闲小宝】新订单成交警报！"
                },
                "template": "red"  # 红色大标题，极其醒目！
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**🛍️ 售出商品**：{item_name}\n**💰 订单金额**：¥{price}\n**👤 买家账号**：{buyer_email}\n**📍 配送地址**：{address}\n**⏰ 交易时间**：刚刚"
                    }
                },
                {"tag": "hr"},
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "📦 立刻发货"},
                            "type": "primary"
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "💬 联系买家"},
                            "type": "default"
                        }
                    ]
                }
            ]
        }
    }
    
    try:
        response = requests.post(webhook_url, json=payload)
        print(f"✅ [黑灯工厂] 飞书告警发送成功！状态码: {response.status_code}")
        return "Webhook Alert Sent!"
    except Exception as e:
        print(f"⚠️ [黑灯工厂] 飞书告警发送失败: {e}")
        return "Webhook Alert Failed!"