import re
with open("src/posts/router.py", "r") as f:
    text = f.read()

text = text.replace("for msg in request.history:", "for msg in (request.history or request.messages or []):")
text = text.replace("收到包含 {len(request.history)} 条记忆的对话请求", "收到包含 {len(request.history or request.messages or [])} 条记忆的对话请求")

with open("src/posts/router.py", "w") as f:
    f.write(text)
