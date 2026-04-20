import re

with open("src/posts/router.py", "r", encoding="utf-8") as f:
    text = f.read()

# I will replace the block with pure variables
# 1. 570
text = text.replace(
    r"""yield f"data: {json.dumps({'content': '\n\n🕸️ [LangGraph] 正在启动量子爬虫进行全网比价，请稍候...'})}\n\n"""",
    """resp_1 = {'content': '\\n\\n🕸️ [LangGraph] 正在启动量子爬虫进行全网比价，请稍候...'}
                    yield f"data: {json.dumps(resp_1)}\\n\\n\""""
)

# 2. 572
text = text.replace(
    r"""yield f"data: {json.dumps({'content': '\n\n📦 [LangGraph] 正在为您查验库存并生成订单...'})}\n\n"""",
    """resp_2 = {'content': '\\n\\n📦 [LangGraph] 正在为您查验库存并生成订单...'}
                    yield f"data: {json.dumps(resp_2)}\\n\\n\""""
)

with open("src/posts/router.py", "w", encoding="utf-8") as f:
    f.write(text)

