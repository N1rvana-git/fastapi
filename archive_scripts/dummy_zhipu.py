import re

with open("src/posts/agent_tools.py", "r") as f:
    text = f.read()

# remove Zhipu import
text = text.replace("from zhipuai import ZhipuAI", "")

# remove Zhipu initialization
text = re.sub(r'ai_client\s*=\s*ZhipuAI\(.*?\)', '', text)

# Mock search_platform_products_tool
text = re.sub(
    r'@tool\("search_platform_products", args_schema=SearchProductsInput\)\s*async def search_platform_products_tool\(query: str\) -> str:.*?except Exception as e:.*?return "数据库检索暂时不可用，请告诉用户系统正在维护。"',
    '''@tool("search_platform_products", args_schema=SearchProductsInput)
async def search_platform_products_tool(query: str) -> str:
    """
    🚨【核心工具】当用户询问“你们这里有什么商品”、“我想买个XXX”、“帮我推荐XXX”时，必须调用此工具！
    该工具会通过 AI 向量数据库（pgvector）在平台的真实库存中进行语义检索。
    """
    print(f"⚡ [Tool 触发] 正在检索平台数据库，搜索词: '{query}'")
    return "商品库检索（Zhipu Embedding）已被彻底关闭。请直接告诉用户目前无法查询本地商品库存。"''',
    text,
    flags=re.DOTALL
)

# Mock search_platform_policy_tool
text = re.sub(
    r'@tool\("search_platform_policy", args_schema=SearchKnowledgeInput\)\s*async def search_platform_policy_tool\(query: str\) -> str:.*?print\(f"❌ \[知识库检索报错\] {e}"\)',
    '''@tool("search_platform_policy", args_schema=SearchKnowledgeInput)
async def search_platform_policy_tool(query: str) -> str:
    """
    🚨【必杀技能】当且仅当用户询问关于：退货、换货、防骗、运费、平台规则、客服介入等【政策/规则类】问题时，必须调用此工具！
    千万不要用查商品的工具去查规则！
    """
    print(f"📖 [翻书引擎触发] 正在知识库中检索规则: '{query}'")
    return "知识库检索（Zhipu Embedding）已被彻底关闭。请直接告诉用户目前无法查询平台规则。"''',
    text,
    flags=re.DOTALL
)

with open("src/posts/agent_tools.py", "w") as f:
    f.write(text)
