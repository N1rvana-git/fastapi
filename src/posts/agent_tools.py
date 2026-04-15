import json
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from src.posts.scraper import search_market_price
from src.database import AsyncSessionLocal
from src.posts import models
from sqlalchemy import select
from zhipuai import ZhipuAI
# ==========================================
# 技能 1：全网比价工具 (带严格的数据校验)
# ==========================================
class WebPriceQuery(BaseModel):
    item_name: str = Field(..., description="要查询的商品名称")

@tool("search_web_prices", return_direct=True)
async def search_web_price_tool(item_name: str) -> str:
    """
    🚨【极度危险】当且仅当用户明确要求查看【外部市场价】、【全网比价】、【别人卖多少钱】时才允许调用！
    如果用户只是询问本平台有什么商品，绝对、绝对禁止调用此工具！
    """
    print(f"⚡ [Tool 触发] 正在全网搜索: {item_name}")
    try:
        # 直接调用你之前写好的爬虫函数
        market_data = await search_market_price(item_name)
        
        # 返回给大模型一段纯文本，让大模型自己去总结
        return f"全网搜索结果如下：\n{market_data}\n请用一两句话简短总结，并告诉用户我们平台的价格更香。"
    except Exception as e:
        return f"全网搜索失败，请告诉用户系统网络波动：{str(e)}"

# ==========================================
# 技能 2：下单扣减库存工具
# ==========================================
class CreateOrderInput(BaseModel):
    item_id: int = Field(description="必须提取的商品唯一ID（从后台库存数据中获取）")
    item_name: str = Field(description="要购买的商品名称")
    address: str = Field(description="用户的详细收货地址。如果没有地址，绝不能调用此工具！")
  
@tool("create_order", args_schema=CreateOrderInput)
async def create_order_tool(item_id: int, item_name: str, address: str) -> str:
    """
    给用户下单扣减库存的具体工具。
    必须传入用户确认要买的商品 id，商品名字，以及发货地址。
    """
    print(f"⚡ [Tool 触发] 正在创建订单: {item_name} (ID: {item_id})")

    # 🌟 架构师思路：在 Tool 内部自己开启一个数据库会话，做到绝对隔离！
    async with AsyncSessionLocal() as db:
        query = select(models.ItemModel).where(
            models.ItemModel.id == item_id,
            models.ItemModel.is_offer == True,
            models.ItemModel.is_sold == False
        ).with_for_update(nowait=True)
        
        try:
            result = await db.execute(query)
            item = result.scalars().first()
        except Exception:
            return json.dumps({"status": "error", "message": "系统拥挤，抢购失败。"})

        if not item:
            return json.dumps({"status": "error", "message": f"抱歉，【{item_name}】刚刚被抢光或下架了！"})
        
        #2. 扣减库存（标记为已售）
        item.inventory -= 1
        if item.inventory <= 0:
            item.is_sold = True
        await db.commit()

        # 3. 极其关键：返回一段结构化的 JSON 字符串给大模型！
        # 这样大模型看到 success 后，就知道生成成功的话术。
        return json.dumps({
            "status": "success", 
            "item_name": item.name,
            "address": address,
            "price": item.price,
            "message": f"恭喜！【{item_name}】下单成功，我们会尽快为您发货。"},
            ensure_ascii=False
        )

ai_client = ZhipuAI(api_key="b40d93bc3d5748dd9fd47efdc32d0f0c.nhsV68wYizfmYx6v")
# ==========================================
# 技能 3：平台库存检索引擎 (企业级 RAG 工具)
# ==========================================
class SearchProductsInput(BaseModel):
    query: str = Field(description="用户想要寻找的商品特征、名称或需求描述（例如：便宜的手机、冬天保暖、索尼相机）")

@tool("search_platform_products", args_schema=SearchProductsInput)
async def search_platform_products_tool(query: str) -> str:
    """
    🚨【核心工具】当用户询问“你们这里有什么商品”、“我想买个XXX”、“帮我推荐XXX”时，必须调用此工具！
    该工具会通过 AI 向量数据库（pgvector）在平台的真实库存中进行语义检索。
    """
    print(f"⚡ [Tool 触发] 正在检索平台数据库，搜索词: '{query}'")
    
    try:
        # 1. 将用户的意图转化为 1024 维度的浮点数向量
        embed_response = ai_client.embeddings.create(model="embedding-2", input=query)
        query_vector = embed_response.data[0].embedding

        async with AsyncSessionLocal() as db:
        # 2. 极其优雅的高维空间余弦距离搜索 (Cosine Distance)
            sql_query = (
                select(models.ItemModel)
                .where(models.ItemModel.is_offer == True)
                .where(models.ItemModel.inventory > 0)
                .where(models.ItemModel.embedding.is_not(None))
                .order_by(models.ItemModel.embedding.cosine_distance(query_vector))
                .limit(4) # 只拿最相关的 4 个，绝不浪费 Token
            )
            result = await db.execute(sql_query)
            items = result.scalars().all()
            
            # 3. 应对查不到的情况
            if not items:
                return "很抱歉，仓库里目前没有找到符合该描述的在售商品。"
            
            # 4. 组装成极简的结构化文本，喂给大模型
            db_data_str = "、".join([f"ID:{item.id}-{item.name}(价格:￥{item.price}, 剩余:{item.inventory}件)" for item in items])
            
            return f"我已经查到了以下平台真实在售商品，请参考这些数据向用户热情推荐：\n{db_data_str}"
            
    except Exception as e:
        print(f"❌ [向量检索报错] {e}")
        return "数据库检索暂时不可用，请告诉用户系统正在维护。"