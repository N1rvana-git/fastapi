import asyncio
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.config import settings
from src.database import AsyncSessionLocal
from src.posts.models import KnowledgeModel
from zhipuai import ZhipuAI
from src.llm_policy import get_embedding_model

zhipu_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)

async def ingest_policy_document():
    # 1. 假设这是老板给你的一份极长的 TXT 文档
    long_text = """
    【闲小宝防骗指南】
    1. 绝不脱离平台交易：如果卖家要求加微信转账，100%是骗子。
    2. 验货规则：收到快递请务必当面拆箱录制视频，如果发现商品破损，请直接拒收。
    【闲小宝退换货政策】
    1. 七天无理由：如果是商家店铺，支持7天无理由退货，邮费由买家承担。
    2. 个人闲置：个人卖家发布的商品，非质量问题不支持退换。如果有纠纷，请在订单页面点击"申请平台客服介入"。
    （...假设这里还有 5000 字的规则...）
    """

    # 🌟 2. 架构师核心：大厂级文本切片机
    # RecursiveCharacterTextSplitter 会非常聪明地尽量按段落、句子来切，而不是把一句话硬生生劈成两半
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=150,     # 每个切片大约 150 个字符
        chunk_overlap=20,   # 切片之间保留 20 个字的重叠，防止上下文语义被切断！
    )
    chunks = text_splitter.split_text(long_text)
    print(f"🔪 文档已被切成了 {len(chunks)} 个小块！")

    # 3. 将每一个小块转化为高维向量，并存入 PostgreSQL
    async with AsyncSessionLocal() as db:
        for chunk in chunks:
            # 调 API 把文本变成 1024 维度的数字
            embed_response = await asyncio.to_thread(
                zhipu_client.embeddings.create,
                model=get_embedding_model(),
                input=chunk,
            )
            vector = embed_response.data[0].embedding
            
            # 存入数据库的知识库表
            new_knowledge = KnowledgeModel(
                title="平台基础规则V1",
                content=chunk,
                embedding=vector
            )
            db.add(new_knowledge)
        await db.commit()
        print("✅ 知识库灌入完成！")