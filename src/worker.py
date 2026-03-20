import os
import time
from celery import Celery
from dotenv import load_dotenv

# 加载环境变量 (确保能读到真实的配置)
load_dotenv()

# ==========================================
# 🏭 1. 建立洗碗厂 (初始化 Celery 实例)
# ==========================================
# 我们雇佣 Redis 作为我们的“传送带 (Broker)”和“结果存放架 (Backend)”
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0") # 默认连 docker-compose 里的 redis

celery_app = Celery(
    "fastapi_heavy_factory",
    broker=REDIS_URL,
    backend=REDIS_URL
)

# ⚙️ 工厂配置项优化 (大厂必备防弹衣)
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='Asia/Shanghai',
    enable_utc=True,
    # 🌟 极其重要：如果洗碗工突然猝死，碗会重新回到传送带上分配给别人！
    task_acks_late=True, 
    worker_prefetch_multiplier=1 # 防止一个洗碗工抢了太多碗洗不完
)

# ==========================================
# 🧑‍🔧 2. 定义车间工人 (编写具体的耗时任务)
# ==========================================

@celery_app.task(bind=True, max_retries=3)
def inject_embedding_task(self, item_id: int, item_name: str):
    """
    车间任务 1：为商品生成 AI 向量 (极其耗费 CPU 和 网络)
    """
    print(f"📦 [向量车间] 开始处理商品 ID:{item_id} [{item_name}] 的向量生成任务...")
    
    try:
        # 模拟生成向量的耗时操作 (比如调用智谱 AI 的 embedding 接口)
        time.sleep(0.1) 
        
        print(f"✅ [向量车间] 商品 ID:{item_id} 向量注入完成！")
        return {"status": "success", "item_id": item_id}
        
    except Exception as exc:
        print(f"❌ [向量车间] 任务崩溃，准备重试: {exc}")
        # 如果调用大模型失败，每隔 5 秒自动重试，最多重试 3 次！
        raise self.retry(exc=exc, countdown=5)

@celery_app.task(bind=True)
def send_feishu_alert_task(self, item_name: str, price: float, user_email: str, address: str):
    """
    车间任务 2：发送飞书发货通知 (耗时网络请求)
    """
    print(f"📧 [通知车间] 正在向飞书发送订单通知！商品: {item_name}, 客户: {user_email}")
    time.sleep(2) # 模拟网络延迟
    print("✅ [通知车间] 飞书消息发送成功！")
    return {"status": "sent"}