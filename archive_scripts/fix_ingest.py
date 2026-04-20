import re

with open('src/posts/ingest_doc.py', 'r') as f:
    text = f.read()

text = text.replace('from zhipuai import AsyncZhipuAI\n', '')
text = text.replace('ai_client = AsyncZhipuAI(api_key=settings.ZHIPUAI_API_KEY)', 'from openai import AsyncOpenAI\nasync_chat_client = AsyncOpenAI(api_key=settings.API_KEy or settings.API_KEY, base_url="https://api.zetatechs.com/v1")')
text = text.replace('ai_client', 'async_chat_client')
text = text.replace('model="embedding-2"', 'model="text-embedding-004"')

with open('src/posts/ingest_doc.py', 'w') as f:
    f.write(text)

