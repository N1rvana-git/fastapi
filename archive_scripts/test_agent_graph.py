import asyncio
from src.posts.agent_graph import graph

async def main():
    res = await graph.ainvoke({"messages": [("user", "仓库里有没有相机卖")]})
    print(res["messages"][-1].content)

asyncio.run(main())
