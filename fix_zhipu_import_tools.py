with open("src/posts/agent_tools.py", "r") as f:
    text = f.read()

# Add missing import for KnowledgeModel
if "KnowledgeModel" not in text:
    text = text.replace("from src.posts import models", "from src.posts import models\nfrom src.posts.models import KnowledgeModel\nfrom src.config import settings")

import re
text = re.sub(r"ai_client\s*=\s*ZhipuAI\(api_key=.*?\)", 'ai_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)', text)

# Inject search_platform_policy_tool which got lost when checking out from master base
policy_tool_str = """
# ==========================================
# 技能 4：企业知识库翻书引擎 (RAG 核心)
# ==========================================
class SearchKnowledgeInput(BaseModel):
    query: str = Field(description="用户询问的规则、防骗、退换货、纠纷等具体问题")

@tool("search_platform_policy", args_schema=SearchKnowledgeInput)
async def search_platform_policy_tool(query: str) -> str:
    \"\"\"
    🚨【必杀技能】当且仅当用户询问关于：退货、换货、防骗、运费、平台规则、客服介入等【政策/规则类】问题时，必须调用此工具！
    千万不要用查商品的工具去查规则！
    \"\"\"
    print(f"📖 [翻书引擎触发] 正在知识库中检索规则: '{query}'")
    try:
        # 1. 将用户的提问转化为向量
        embed_response = ai_client.embeddings.create(model="embedding-2", input=query)
        query_vector = embed_response.data[0].embedding

        async with AsyncSessionLocal() as db:
            # 2. 在知识库表中进行余弦距离搜索，找到最相关的规则文本
            sql_query = (
                select(KnowledgeModel)
                .where(KnowledgeModel.embedding.is_not(None))
                .order_by(KnowledgeModel.embedding.cosine_distance(query_vector))
                .limit(2) # 只拿最相关的 2 条规则
            )
            result = await db.execute(sql_query)
            chunks = result.scalars().all()
            
            if not chunks:
                return "很抱歉，知识库里没有找到相关的规则信息。请告诉用户稍后联系客服获取帮助。"
            
            # 3. 组装给大模型看
            rules_text = "\\n".join([f"片段摘录：{chunk.content}" for chunk in chunks])
            return f"以下是平台官方规定的原文片段。你必须【绝对忠诚】于这些片段来回答用户。\\n禁止编造任何原文中不存在的电话号码、邮箱或网址！如果原文没写联系方式，请让用户点击订单页面的'申请介入'。\\n原文片段：\\n{rules_text}"
    except Exception as e:
        print(f"❌ [知识库检索报错] {e}")
        return "知识库检索暂时不可用，请告诉用户系统正在维护。"

"""

if "search_platform_policy" not in text:
    text += policy_tool_str

# make sure search_web_price_tool has the correct signature since git checkout from master was `search_web_prices` instead of `search_web_price`
text = text.replace('@tool("search_web_prices", return_direct=True)', """
class WebPriceInput(BaseModel):
    item_name: str = Field(description="要购买或查询的商品名称")

@tool("search_web_price", args_schema=WebPriceInput)""")
text = text.replace('class WebPriceQuery(BaseModel):\n    item_name: str = Field(..., description="要查询的商品名称")', '')

with open("src/posts/agent_tools.py", "w") as f:
    f.write(text)
