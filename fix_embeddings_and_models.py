import re
import os

files_to_fix = [
    "src/posts/service.py",
    "src/posts/agent_tools.py",
    "src/posts/ingest_doc.py",
    "src/feishu/router.py"
]

for fd in files_to_fix:
    with open(fd, "r", encoding="utf-8") as f:
        content = f.read()

    # In ingest_doc.py, ai_client was used
    if fd == "src/posts/ingest_doc.py":
        content = content.replace("from zhipuai import AsyncZhipuAI", "from openai import AsyncOpenAI\nfrom src.config import settings")
        content = re.sub(r'ai_client = AsyncZhipuAI\(.*?\)', 'ai_client = AsyncOpenAI(api_key=settings.API_KEy or settings.API_KEY, base_url="https://api.zetatechs.com/v1")', content)

    # In all files: replace ai_client.embeddings.create with chat_client.embeddings.create
    # Except in ingest_doc and router.py where it might be async_chat_client or to_thread
    if "chat_client" in content or "async_chat_client" in content:
        # router.py and service.py already have chat_client logic.
        content = content.replace("ai_client.embeddings.create", "chat_client.embeddings.create")
    else:
        pass # handled for ingest_doc

    # Replace model name
    content = content.replace('model="embedding-2"', 'model="text-embedding-3-small"')

    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)

# Fix models.py Vector dimension 1024 -> 1536
models_file = "src/posts/models.py"
with open(models_file, "r", encoding="utf-8") as f:
    models_content = f.read()
models_content = models_content.replace("Vector(1024)", "Vector(1536)")
with open(models_file, "w", encoding="utf-8") as f:
    f.write(models_content)

print("✅ Files updated.")
