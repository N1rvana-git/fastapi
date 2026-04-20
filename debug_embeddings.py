import asyncio
from zhipuai import ZhipuAI
from src.config import settings

def main():
    ai_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
    try:
        print("Creating embeddings...")
        embed_response = ai_client.embeddings.create(model="embedding-2", input="hello")
        print("Success:", len(embed_response.data[0].embedding))
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("Failed!", type(e), e)

main()
