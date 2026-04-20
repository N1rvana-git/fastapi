import re

files_to_fix = ["src/feishu/router.py", "src/posts/service.py"]

for fd in files_to_fix:
    with open(fd, "r") as f:
        content = f.read()

    # Add OpenAI client to import
    if "from openai import OpenAI" not in content and "from openai import AsyncOpenAI" not in content:
        content = content.replace("from zhipuai import ZhipuAI", "from zhipuai import ZhipuAI\nfrom openai import OpenAI, AsyncOpenAI\nfrom src.config import settings")
    
    # Initialize the OpenAI client below zhipu
    content = re.sub(
        r'(ai_client\s*=\s*ZhipuAI.*?\))',
        r'\1\nchat_client = OpenAI(api_key=settings.API_KEy or settings.API_KEY, base_url="https://api.zetatechs.com/v1")\nasync_chat_client = AsyncOpenAI(api_key=settings.API_KEy or settings.API_KEY, base_url="https://api.zetatechs.com/v1")',
        content,
        count=1
    )

    # Change the model and the client in calls
    content = content.replace("ai_client.chat.completions.create", "chat_client.chat.completions.create")
    content = content.replace('model="GLM-4-Flash-250414"', 'model="gemini-3-flash-preview-free"')

    # Async ones in feishu/router.py need to await asyncio.to_thread with sync client, OR just use chat_client. Since the code used asyncio.to_thread(ai_client.chat.completions.create), it works with sync chat_client too!
    
    with open(fd, "w") as f:
        f.write(content)
