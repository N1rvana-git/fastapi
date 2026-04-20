import re
with open("src/posts/agent_tools.py", "r", encoding="utf-8") as f:
    text = f.read()

if "from openai import OpenAI" not in text:
    text = text.replace("from zhipuai import ZhipuAI", "from openai import OpenAI\nfrom zhipuai import ZhipuAI")

text = re.sub(
    r'ai_client\s*=\s*ZhipuAI\([^)]+\)',
    'chat_client = OpenAI(api_key=settings.API_KEy or settings.API_KEY, base_url="https://api.zetatechs.com/v1")',
    text
)
with open("src/posts/agent_tools.py", "w", encoding="utf-8") as f:
    f.write(text)
print("Done fix agent_tools")
