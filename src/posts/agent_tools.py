import json
import asyncio
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from src.posts.scraper import search_market_price
from src.database import AsyncSessionLocal
from src.posts import models
from sqlalchemy import select
from zhipuai import ZhipuAI

from src.posts.models import KnowledgeModel
from src.config import settings
from src.llm_policy import get_embedding_model

zhipu_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
# ==========================================
# 技能 1：全网比价工具 (带严格的数据校验)
# ==========================================
class WebPriceInput(BaseModel):
    item_name: str = Field(description="要购买或查询的商品名称")

@tool("search_web_price", args_schema=WebPriceInput)
async def search_web_price_tool(item_name: str) -> str:
    """
    🚨【全网搜索工具】当用户要求“全网比价”、“外面卖多少钱”时调用。
    该工具将启动无头浏览器（Playwright）前往全网抓取真实的市场价格。
    """
    print(f"🕸️ [Playwright 启动] 正在深入暗网抓取 {item_name} 的底价...")
    try:
        # 直接调用你极其强大的 Playwright 爬虫！
        market_data = await search_market_price(item_name)
        
        return f"Playwright 抓取到的全网真实数据如下：\n{market_data}\n请用一两句话简短总结，并突出我们平台的价格优势。"
    except Exception as e:
        return f"浏览器抓取失败：{str(e)}"

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
        embed_response = await asyncio.to_thread(
            zhipu_client.embeddings.create,
            model=get_embedding_model(),
            input=query,
        )
        query_vector = embed_response.data[0].embedding
    except Exception as e:
        return f"商品向量检索失败：{e}"

    async with AsyncSessionLocal() as db:
        vector_query = (
            select(models.ItemModel)
            .where(models.ItemModel.is_offer == True)
            .where(models.ItemModel.inventory > 0)
            .where(models.ItemModel.embedding.is_not(None))
            .order_by(models.ItemModel.embedding.cosine_distance(query_vector))
            .limit(5)
        )
        result = await db.execute(vector_query)
        items = list(result.scalars().all())

        if not items:
            fallback_query = (
                select(models.ItemModel)
                .where(models.ItemModel.is_offer == True)
                .where(models.ItemModel.inventory > 0)
                .limit(5)
            )
            items = list((await db.execute(fallback_query)).scalars().all())

    if not items:
        return "当前没有可推荐的在售商品。"

    lines = [f"ID:{item.id} | {item.name} | 价格:￥{item.price} | 库存:{item.inventory}" for item in items]
    return "平台推荐商品如下：\n" + "\n".join(lines)

# ==========================================
# 技能 4：企业知识库翻书引擎 (RAG 核心)
# ==========================================
class SearchKnowledgeInput(BaseModel):
    query: str = Field(description="用户询问的规则、防骗、退换货、纠纷等具体问题")

@tool("search_platform_policy", args_schema=SearchKnowledgeInput)
async def search_platform_policy_tool(query: str) -> str:
    """
    🚨【必杀技能】当且仅当用户询问关于：退货、换货、防骗、运费、平台规则、客服介入等【政策/规则类】问题时，必须调用此工具！
    千万不要用查商品的工具去查规则！
    """
    print(f"📖 [翻书引擎触发] 正在知识库中检索规则: '{query}'")
    try:
        embed_response = await asyncio.to_thread(
            zhipu_client.embeddings.create,
            model=get_embedding_model(),
            input=query,
        )
        query_vector = embed_response.data[0].embedding
    except Exception as e:
        return f"知识库向量检索失败：{e}"

    async with AsyncSessionLocal() as db:
        vector_query = (
            select(KnowledgeModel)
            .where(KnowledgeModel.embedding.is_not(None))
            .order_by(KnowledgeModel.embedding.cosine_distance(query_vector))
            .limit(3)
        )
        result = await db.execute(vector_query)
        docs = list(result.scalars().all())

    if not docs:
        return "知识库暂无可用规则，请稍后再试。"

    snippets = [f"- {doc.content[:180]}" for doc in docs]
    return "匹配到的平台规则：\n" + "\n".join(snippets)