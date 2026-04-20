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

    # Revert chat_client.embeddings back to ai_client.embeddings
    content = content.replace("chat_client.embeddings.create", "ai_client.embeddings.create")
    if fd == "src/posts/ingest_doc.py":
        content = content.replace("from openai import AsyncOpenAI", "from zhipuai import AsyncZhipuAI")
        content = re.sub(r'ai_client\s*=\s*AsyncOpenAI\(.*?\)', 'ai_client = AsyncZhipuAI(api_key=settings.ZHIPUAI_API_KEY)', content)
    
    content = content.replace('model="text-embedding-3-small"', 'model="embedding-2"')

    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)

# Revert models.py
models_file = "src/posts/models.py"
with open(models_file, "r", encoding="utf-8") as f:
    models_content = f.read()
models_content = models_content.replace("Vector(1536)", "Vector(1024)")
with open(models_file, "w", encoding="utf-8") as f:
    f.write(models_content)
