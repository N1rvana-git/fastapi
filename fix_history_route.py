import sys

with open("src/posts/router.py", "r", encoding="utf-8") as f:
    content = f.read()

# FastAPI trailing slash redirect issue:
# By default, `/ai/history` and `/ai/history/` are different. If you access `/ai/history/`, it returns 307 temporary redirect.
# With DELETE method, the browser doesn't automatically follow 307 redirect using DELETE, but uses GET instead or drops payload.
# So let's make it accept trailing slashes for ai history and also agent.

content = content.replace('@router.delete("/ai/history")', '@router.delete("/ai/history/")')
content = content.replace('@router.get("/ai/history")', '@router.get("/ai/history/")')

with open("src/posts/router.py", "w", encoding="utf-8") as f:
    f.write(content)
