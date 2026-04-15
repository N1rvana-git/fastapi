from typing import Annotated, TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition
from langchain_zhipu import ChatZhipuAI
from langchain_core.messages import SystemMessage

# 引入我们刚写好的工具
from src.posts.agent_tools import search_web_price_tool, create_order_tool,search_platform_products_tool
from src.config import settings # 确保这里能拿到你的 ZHIPUAI_API_KEY

# 1. 定义状态 (State)

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]

tools = [search_web_price_tool, create_order_tool,search_platform_products_tool]
tool_node = ToolNode(tools=tools)

llm = ChatZhipuAI(
    api_key="b40d93bc3d5748dd9fd47efdc32d0f0c.nhsV68wYizfmYx6v", 
    model="glm-4.5-flash",
    temperature=0.2,
    streaming=True
)

llm_with_tools = llm.bind_tools(tools)
# 4. 定义大模型思考的节点 (Node)
async def chatbot_node(state: AgentState):
    print("🤖 [Node] 大模型正在思考...")
    response = await llm_with_tools.ainvoke(state["messages"])
    return {"messages": [response]}

# ==========================================
# 🌟 5. 拼装神兵利器 (构建 Graph)
# ==========================================
# 实例化一个状态图

workflow = StateGraph(AgentState)

workflow.add_node("chatbot", chatbot_node)
workflow.add_node("tools", tool_node)

workflow.add_edge(START,"chatbot")

# 🌟 魔法路由：当 chatbot 思考完毕后，该去哪？
# tools_condition 会自动判断：如果大模型决定调用工具，就路由到 "tools" 节点；如果只是纯聊天，就路由到 END 结束。
workflow.add_conditional_edges(
    "chatbot",
    tools_condition,
)

# 工具执行完毕后，必须带着工具的结果，强制流转回 chatbot，让它看看执行结果，给出最终回复！
workflow.add_edge("tools", "chatbot")

# 编译成可执行的图！
graph = workflow.compile()

# 如果你想看看你画的图长什么样，你可以解开下面这行在独立测试时运行：
# print(graph.get_graph().draw_ascii())