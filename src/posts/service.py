#核心业务逻辑
from .schemas import ItemCreate, ItemUpdate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from . import schemas
from . import models
from .utils import get_password_hash
import json
from openai import OpenAI, AsyncOpenAI
from zhipuai import ZhipuAI
from src.config import settings
from src.llm_policy import get_chat_base_url, get_chat_model, get_embedding_model, get_proxy_api_key
from src.posts.scraper import search_market_price
from src.worker import send_feishu_alert_task
from src.posts.prompts import SALES_AGENT_SYSTEM_PROMPT
from src.posts.models import UserModel
from src.posts.schemas import UserCreate
# 实例化大模型客户端
chat_client = OpenAI(api_key=get_proxy_api_key(), base_url=get_chat_base_url())
async_chat_client = AsyncOpenAI(api_key=get_proxy_api_key(), base_url=get_chat_base_url())
zhipu_client = ZhipuAI(api_key=settings.ZHIPUAI_API_KEY)
async def create_item(db: AsyncSession, item: schemas.ItemCreate, owner_id: int) -> models.ItemModel:
    """创建物品，自动关联owner_id"""
    item_data = item.model_dump(exclude={"tag_ids"})  # 先排除标签 ID，后面单独处理
    db_item = models.ItemModel(**item_data, owner_id=owner_id)

    if item.tag_ids:
        tags = await get_tags_by_ids(db, item.tag_ids)
        db_item.tags = list(tags)
    
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

async def get_item(db: AsyncSession, item_id: int) -> models.ItemModel | None:
    """根据 ID 查找物品"""
    result = await db.execute(select(models.ItemModel).where(models.ItemModel.id == item_id))
    return result.scalars().one_or_none()

async def delete_item(db: AsyncSession, item: models.ItemModel):
    """删除物品"""
    await db.delete(item)
    await db.commit()

async def update_item(db: AsyncSession, db_item: models.ItemModel, item_update: schemas.ItemUpdate):
    """更新物品逻辑"""
    # 只提取用户真正传了的字段
    update_data = item_update.model_dump(exclude_unset=True,exclude={"tag_ids"})
    
    # 遍历字典，更新数据库对象
    for key, value in update_data.items():
        setattr(db_item, key, value)

    # 检查是否需要更新标签
    if item_update.tag_ids is not None:
        tags = await get_tags_by_ids(db, item_update.tag_ids)
        db_item.tags = list(tags)

    # 如果更新了库存，自动同步 is_sold 状态
    if hasattr(db_item, "inventory"):
        if db_item.inventory > 0:
            db_item.is_sold = False
        else:
            db_item.is_sold = True

    # 提交保存
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

async def get_tag_by_name(db: AsyncSession, name: str):
    query = select(models.item_TagModel).where(models.item_TagModel.name == name)
    result = await db.execute(query)
    return result.scalars().first()

async def create_tag(db: AsyncSession, tag_name: str) -> models.item_TagModel:
    existing_tag = await get_tag_by_name(db, tag_name)
    if existing_tag:
        return existing_tag
    
    try:
        db_tag = models.item_TagModel(name=tag_name)#创建新标签
        db.add(db_tag)
        await db.commit()
        await db.refresh(db_tag)
        return db_tag
    except IntegrityError:
        await db.rollback()
        # If create failed due to race condition, return existing
        existing = await get_tag_by_name(db, tag_name)
        if existing:
            return existing
        raise # Re-raise if it's some other integrity error

async def get_tags_by_ids(db: AsyncSession, tag_ids: list[int]):
    if not tag_ids:
        return []
    result = await db.execute(select(models.item_TagModel).where(models.item_TagModel.id.in_(tag_ids)))
    return result.scalars().all()

async def get_user_by_feishu_id(db: AsyncSession, feishu_open_id: str) -> models.UserModel | None:
    """
    🔍 技能 1：看牌认人
    根据飞书传过来的 open_id，去数据库里捞出我们平台的真实用户。
    如果没找到，就返回 None。
    """
    result = await db.execute(
        select(models.UserModel).where(models.UserModel.feishu_open_id == feishu_open_id)
    )
    return result.scalar_one_or_none()


async def bind_feishu_account(db: AsyncSession, user_id: int, feishu_open_id: str) -> models.UserModel:
    """
    🤝 技能 2：发牌登记 (绑定账号)
    把飞书访客牌，钉在这个业主的档案上！
    """
    # 1. 先把我们平台的业主找出来 (复用你上面写好的 get_user 函数)
    user = await db.execute(select(models.UserModel).where(models.UserModel.id == user_id)); user = user.scalar_one_or_none()
    
    # 2. 给他贴上飞书的标签
    user.feishu_open_id = feishu_open_id
    
    # 3. 盖章确认，存入档案库 (数据库提交)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    
    return user

# =====================================================================
# 🧑‍🍳 AI 中央厨房：统一处理所有端的大模型逻辑 (RAG + Tools + Memory)
# =====================================================================
async def ask_ai_agent(db: AsyncSession, current_user: models.UserModel, user_text: str, history_list: list = None):
    history_list = history_list or []
    
    # 1. 💾 存用户消息进数据库
    new_user_record = models.AIChatRecord(user_id=current_user.id, role="user", content=user_text)
    db.add(new_user_record)
    await db.commit()
    # 2. 🔫 语境融合与向量检索 (RAG)
    user_history_texts = [
        msg.content if hasattr(msg, "content") else msg.get("content", "") if isinstance(msg, dict) else ""
        for msg in history_list
        if (msg.role if hasattr(msg, "role") else msg.get("role", "") if isinstance(msg, dict) else "") == "user"
    ]
    recent_user_texts = user_history_texts[-3:]
    search_query = " ".join(recent_user_texts) + " " + user_text

    print(f"🔫 [中央厨房] 正在为您检索库存: '{search_query}'")
    try:
        embed_response = zhipu_client.embeddings.create(model=get_embedding_model(), input=search_query)
        query_vector = embed_response.data[0].embedding

        query = select(models.ItemModel).where(models.ItemModel.is_offer == True).where(models.ItemModel.inventory > 0).where(models.ItemModel.embedding.is_not(None)).order_by(models.ItemModel.embedding.cosine_distance(query_vector)).limit(3)
        result = await db.execute(query)
        items = list(result.scalars().all())
        
        if not items:
            backup_query = select(models.ItemModel).where(models.ItemModel.inventory > 0).limit(5)
            items = (await db.execute(backup_query)).scalars().all()
            
        db_data_str = "当前没有任何商品。" if not items else "、".join([f"ID:{item.id}-{item.name}(￥{item.price}, 剩余{item.inventory}件)" for item in items])
    except Exception as e:
        db_data_str = "库存检索失败"

    # 3. 🛡️ 构建状态机与 Tools
    messages = [{"role": "system", "content": SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)}]
    
    for msg in history_list[-6:]:
        role = getattr(msg, "role", "user") if hasattr(msg, "role") else msg.get("role", "user")
        content = getattr(msg, "content", "") if hasattr(msg, "content") else msg.get("content", "")
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_text})

    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_web_price",
                "description": "🚨当且仅当用户明确要求查看【外部市场价】、【全网比价】时才允许调用！",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer"},
                        "item_name": {"type": "string"},
                        "address": {"type": "string"}
                    },
                    "required": ["item_id", "item_name", "address"]
                }
            }
        },
        # 注意：这里你可以把你原来那个 create_order 的 tool 定义加回来，为了代码精简我先略写了。
        # 如果你原来的 router 里有 create_order 的字典定义，请务必把它加进这个列表里！
    ]

    # 4. 🧠 开启大模型思考流水线
    print("🤖 [中央厨房] 开启水龙头！向云端大脑发送请求...")
    response = chat_client.chat.completions.create(
        model=get_chat_model(),
        messages=messages,
        tools=tools,
        stream=True  
    )
    
    tool_call_name = ""
    tool_call_args = ""
    full_reply_text = ""

    for chunk in response:
        delta = chunk.choices[0].delta
        if delta.tool_calls:
            tc = delta.tool_calls[0]
            if tc.function.name: tool_call_name += tc.function.name
            if tc.function.arguments: tool_call_args += tc.function.arguments
            yield {"type": "keep-alive"} # 🌟 标准快餐盒：保活包
        elif delta.content:
            full_reply_text += delta.content
            yield {"type": "text", "content": delta.content} # 🌟 标准快餐盒：文字包

    # 5. ⚡ 处理工具调用 (Function Calling)
    if tool_call_name == "search_web_price":
        args = json.loads(tool_call_args)
        item_name = args.get("item_name", "")
        
        yield {"type": "text", "content": f"\n\n🕸️ 正在启动量子爬虫，潜入全网为您搜索 **{item_name}** 的底价..."}
        market_data = await search_market_price(item_name)
        
        summary_response = chat_client.chat.completions.create(
            model=get_chat_model(),
            messages=[{"role": "user", "content": f"简短总结以下价格情报：\n{market_data}"}],
            temperature=0.3
        )
        summary_text = summary_response.choices[0].message.content
        
        # 🌟 标准快餐盒：高级卡片包！
        yield {"type": "card", "card_type": "price_card", "item_name": item_name, "marketPriceSummary": summary_text}
        full_reply_text += f"\n[已展示 {item_name} 的全网价格卡片]\n{summary_text}"

    # 6. 💾 保存 AI 最终回复
    new_ai_record = models.AIChatRecord(user_id=current_user.id, role="assistant", content=full_reply_text)
    db.add(new_ai_record)
    await db.commit()

"""查户口：看看这个邮箱注册过没有"""
async def get_user_by_email(db: AsyncSession, email: str):
    result = await db.execute(select(UserModel).where(UserModel.email == email))
    return result.scalar_one_or_none()

"""造户口：将新用户写入数据库"""
async def create_user(db: AsyncSession, user: UserCreate):
    hashed_password = get_password_hash(user.password)
    db_user = UserModel(
        email=user.email,
        username=user.email.split("@")[0],  # 满足数据库默认字段要求
        age=18,                             # 满足 age 非空约束
        hashed_password=hashed_password, 
        role=user.role)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user