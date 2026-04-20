from typing import Annotated, TypedDict
import logging

# 尝试导入 langgraph；若缺失则降级为轻量 stub，避免启动时报错
try:
    from langgraph.graph import StateGraph, START, END
    from langgraph.graph.message import add_messages
    from langgraph.prebuilt import ToolNode, tools_condition
    LANGGRAPH_AVAILABLE = True
except Exception as _e:
    logging.getLogger(__name__).warning("langgraph not available: %s", _e)
    LANGGRAPH_AVAILABLE = False

    def add_messages(x):
        return x

    class ToolNode:
        def __init__(self, tools=None):
            pass

    def tools_condition(*args, **kwargs):
        return False

    class StateGraph:
        def __init__(self, *args, **kwargs):
            pass
        def add_node(self, *args, **kwargs):
            pass
        def add_edge(self, *args, **kwargs):
            pass
        def add_conditional_edges(self, *args, **kwargs):
            pass
        def compile(self):
            return None

from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage

# 引入本地工具
from src.posts.agent_tools import create_order_tool, search_platform_products_tool, search_platform_policy_tool, search_web_price_tool
from src.config import settings
from src.llm_policy import get_chat_base_url, get_chat_model, get_proxy_api_key
import os

# 1. 定义状态 (State)
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

# 1) 本地工具库，加入我们最强的 Playwright 外挂
local_tools = [create_order_tool, search_platform_products_tool, search_platform_policy_tool, search_web_price_tool]

# 2) 使用中转平台的 Gemini 模型
llm = ChatOpenAI(
    api_key=get_proxy_api_key(),
    base_url=get_chat_base_url(),
    model=get_chat_model(),
    temperature=0.1,
    streaming=True
)

# 3) 绑定本地工具
llm_with_tools = llm.bind_tools(local_tools)

# 4) 将本地工具装载给 ToolNode
tool_node = ToolNode(local_tools)

# 5) 定义大模型思考的节点 (Node)
async def chatbot_node(state: AgentState):
    print("🤖 [Node] 大模型正在思考...")
    try:
        response = await llm_with_tools.ainvoke(state["messages"])
    except Exception as e:
        print(f"⚠️ [Agent 降级] LLM 调用失败，返回安全降级回复。原因: {e}")
        response = AIMessage(content="抱歉，AI 服务暂时波动，请稍后重试。您也可以先问我平台在售商品，我会优先按库存数据为您推荐。")
    return {"messages": [response]}

# ==========================================
# 🌟 6. 拼装神兵利器 (构建 Graph)
# ==========================================
workflow = StateGraph(AgentState)

workflow.add_node("chatbot", chatbot_node)
workflow.add_node("tools", tool_node)

workflow.add_edge(START, "chatbot")

# 🌟 魔法路由：如果大模型决定调用工具，去 "tools"；否则结束。
workflow.add_conditional_edges(
    "chatbot",
    tools_condition,
)

# 工具执行完毕后，必须强制流转回 chatbot，让它根据执行结果给出最终回复
workflow.add_edge("tools", "chatbot")

# 编译成可执行的图
graph = workflow.compile()
