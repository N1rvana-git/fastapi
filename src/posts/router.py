from .scraper import search_market_price
import os
import asyncio
import shutil
from fastapi import APIRouter, Depends, Query, HTTPException,File, UploadFile, Form,BackgroundTasks,status,WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError,OperationalError
from typing import List, Optional
from sqlalchemy import select
from . import schemas
from . import service
from . import models
from .dependencies import get_db_session
from src.auth.dependencies import get_current_user
import asyncio
import json
from src.config import settings
import redis.asyncio as aioredis
from sqlalchemy import select,func,delete,desc
from sqlalchemy.orm import selectinload
from .storage import current_storage
from .dependencies import get_db_session
from openai import AsyncOpenAI
from pydantic import BaseModel
from zhipuai import ZhipuAI
from fastapi.responses import StreamingResponse
from src.worker import inject_embedding_task,send_feishu_alert_task
from .prompts import SALES_AGENT_SYSTEM_PROMPT
router = APIRouter(
    prefix="/items",
    tags=["items"]
)

redis_client = aioredis.Redis(host='redis', port=6379, db=0, decode_responses=True)
# === 🌟 架构师引擎：WebSocket 全局连接池 ===
class ConnectionManager:
    def __init__(self):
        # 存放所有当前在线用户的长连接
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        # 遍历所有在线用户，群发消息！
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass # 如果有人掉线了就跳过

manager = ConnectionManager()

# === 🌟 交易大厅 WebSocket 接入点 ===
@router.websocket("/ws/hall")
async def websocket_endpoint(websocket: WebSocket):
    # 用户一打开网页，就接通并注册到连接池
    await manager.connect(websocket)
    try:
        while True:
            # 保持线路畅通，等待前端发来的心跳包
            await websocket.receive_text() 
    except WebSocketDisconnect:
        # 用户关闭网页，自动将其移出连接池
        manager.disconnect(websocket)
#定义一个极其耗时的后台任务
async def ai_image_review(filename: str):
    print(f"⏳ [AI 审核开始] 正在审核图片：{filename}...")
    await asyncio.sleep(5)  # 模拟 AI 审核时间
    print(f"✅ [AI 审核完成] 图片审核完成：{filename}")

@router.post("/", response_model=schemas.Item)
async def create_new_item(
    item: schemas.ItemCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_session),
    current_user: models.UserModel = Depends(get_current_user)
):
    """创建接口：极速响应，重活甩给 Celery"""
    # 1. 瞬间存入数据库基础信息
    db_item = await service.create_item(db=db, item=item, owner_id=current_user.id)

    # === 🌟 架构师魔法：瞬间将任务甩给后台 Redis 队列！ ===
    print(f"📦 [主线程] 商品基本信息保存成功，已将向量注入任务丢给 Celery！")
    
    # 使用 .delay() 异步投递！主线程绝不停留！
    inject_embedding_task.delay(db_item.id, db_item.name)
    # ===================================================

    return db_item

# 一个用来处理图片的普通函数
async def process_image_in_background(filename: str):
    """模拟一个耗时的图片处理任务"""
    print(f"⏳ [后台任务开始] 正在处理图片：{filename}...")
    await asyncio.sleep(5)  # 模拟处理时间
    print(f"✅ [后台任务完成] 图片处理完成：{filename}")

@router.post("/upload-image/")
async def upload_image(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks  # 注意不要带括号
):
    """专门的图片上传接口 (现在通过统一 Storage 策略处理)"""
    
    # 🌟 核心：把文件直接丢给大管家，不用管它是存本地还是存云端！
    image_url = await current_storage.upload(file)
    
    # 依然保留后台处理任务
    background_tasks.add_task(process_image_in_background, filename=file.filename)
    
    return {
        "filename": file.filename, 
        "url": image_url,  # 🌟 直接返回管家给的网址
        "message": "图片上传成功，正在后台处理..."
    }
@router.get("/")
async def read_items_from_db(
    skip: int = 0,
    limit: int = 8,
    search: Optional[str] = None,
    is_offer_filter: Optional[bool] = None,
    db: AsyncSession = Depends(get_db_session)
):
    print(f"🔍 [查询参数] skip={skip}, limit={limit}, search='{search}', is_offer_filter={is_offer_filter}")

    # 1.构造一个查询图纸 (前端要求显示所有商品，无论是否有库存)
    query = select(models.ItemModel)
    if is_offer_filter is not None:
        query = query.where(models.ItemModel.is_offer == is_offer_filter)
    if search:
        query = query.where(models.ItemModel.name.ilike(f"%{search}%"))

    # 计算总数
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # 获取分页数据
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    
    # === 🌟 架构师级修复：精准切除不需要发给前端的庞大向量数据 ===
    safe_items = []
    for item in items:
        safe_items.append({
            "id": item.id,
            "name": item.name,
            "price": item.price,
            "is_offer": item.is_offer,
            "is_sold": item.is_sold,
            "image_path": item.image_path,
            "inventory": item.inventory
            # 🚨 绝对不把 item.embedding 塞进来，防止序列化爆炸！
        })

    return {
        "total": total,
        "items": safe_items
    }

@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: models.UserModel = Depends(get_current_user)
):
    """删除接口"""
    # 1. 先把物品查出来
    db_item = await service.get_item(db=db, item_id=item_id)
    
    # 2. 如果物品不存在，报 404
    if db_item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # 3. 核心权限检查：如果物品的主人不是当前登录用户，报 403
    if db_item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this item")
    
    # 4. 执行删除
    await service.delete_item(db=db, item=db_item)
    return None

@router.put("/{item_id}", response_model=schemas.Item)
async def update_item(
    item_id: int,
    item_update: schemas.ItemUpdate,
    db: AsyncSession = Depends(get_db_session),
    current_user: models.UserModel = Depends(get_current_user)
):
    """更新接口 (PUT)"""
    # 1. 先查
    db_item = await service.get_item(db=db, item_id=item_id)
    
    # 2. 判空
    if db_item is None:
        raise HTTPException(status_code=404, detail="Item not found")
    
    # 3. 查权限 (只有主人能改)
    if db_item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to update this item")
    
    # 4. 执行更新
    updated_item = await service.update_item(db=db, db_item=db_item, item_update=item_update)
    return updated_item

@router.post("/tags/", response_model=schemas.Tag)
async def create_tag(
    tag: schemas.TagCreate,
    db: AsyncSession = Depends(get_db_session),
    current_user: models.UserModel = Depends(get_current_user)
):
    """创建标签接口"""
    db_tag = await service.create_tag(db=db, tag_name=tag.name)
    return db_tag

@router.get("/tags/")
async def read_tags(db: AsyncSession = Depends(get_db_session)):
    """查询标签列表接口 (加入了 1 毫秒极速 Redis 缓存)"""
    
    # 🌟 1. 尝试从 Redis 内存中找找看有没有叫 "all_tags" 的缓存
    cached_tags = await redis_client.get("all_tags")
    
    if cached_tags:
        # 如果缓存里有，直接起飞！不用去打扰 PostgreSQL 数据库
        print("🚀 [缓存命中] 直接从 Redis 内存秒回数据！")
        return json.loads(cached_tags) 
        
    # 🌟 2. 如果缓存里没有（比如第一次访问，或者缓存过期了）
    print("🐢 [缓存未命中] 内存里没有，老老实实去查 PostgreSQL 数据库...")
    result = await db.execute(select(models.item_TagModel))  
    tags = result.scalars().all()
    
    # 🌟 3. 把查出来的数据整理一下，存一份到 Redis 里
    tags_list = [{"id": tag.id, "name": tag.name} for tag in tags]
    
    # 存入 Redis，并且设置 ex=60，意思是这层缓存只存活 60 秒！
    await redis_client.set("all_tags", json.dumps(tags_list), ex=60)
    
    return tags_list


@router.post("/tags/", status_code=status.HTTP_201_CREATED)
async def add_tag(
    tag_in: schemas.TagCreate, 
    db: AsyncSession = Depends(get_db_session), 
    current_user: models.UserModel = Depends(get_current_user)
):
    """
    添加新标签
    """
    tag_name = tag_in.name.strip()
    if not tag_name:
        raise HTTPException(status_code=400, detail="标签名不能为空")

    result = await db.execute(select(models.item_TagModel).filter(models.item_TagModel.name == tag_name))
    existing_tag = result.scalars().first()
    if existing_tag:
        raise HTTPException(status_code=400, detail="该标签已存在，请换一个名字")

    new_tag = models.item_TagModel(name=tag_name)
    db.add(new_tag)
    await db.commit()
    await db.refresh(new_tag)
    
    # 清除 Redis 缓存
    if redis_client:
        await redis_client.delete("all_tags")
        
    return new_tag


@router.delete("/tags/{tag_id}")
async def delete_tag(
    tag_id: int, 
    db: AsyncSession = Depends(get_db_session), 
    current_user: models.UserModel = Depends(get_current_user)
):
    """
    删除标签
    """
    result = await db.execute(select(models.item_TagModel).filter(models.item_TagModel.id == tag_id))
    tag = result.scalars().first()
    if not tag:
        raise HTTPException(status_code=404, detail="标签不存在或已被删除")

    await db.delete(tag)
    await db.commit()
    
    # 清除 Redis 缓存
    if redis_client:
        await redis_client.delete("all_tags")
        
    return {"message": "标签删除成功"}

#多对多收藏/取消收藏接口
@router.post("/{item_id}/favorite")
async def toggle_favorite(
    item_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: models.UserModel = Depends(get_current_user)
):
    """收藏/取消收藏接口"""
    # 1. 先把物品查出来
    query = (
        select(models.ItemModel)
        .options(selectinload(models.ItemModel.favourited_by))
        .where(models.ItemModel.id == item_id)
    )
    result = await db.execute(query)
    item = result.scalars().first()
    
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在")
    
    #2.提取出已经收藏了这个商品的所有用户 ID
    favorited_user_ids = {user.id for user in item.favourited_by}
    if current_user.id in favorited_user_ids:
        # 已经收藏了，执行取消收藏
        user_to_remove = [user for user in item.favourited_by if user.id == current_user.id]
        item.favourited_by.remove(user_to_remove[0])  # 从收藏列表中移除当前用户
        action_msg = "取消收藏成功"
    else:
        # 没有收藏，执行收藏
        item.favourited_by.append(current_user)
        action_msg  = "收藏成功"

    #3. 提交数据库事务
    await db.commit()
    return {"message": action_msg}

#新增核心交易链路：安全下单接口 (带防超卖悲观锁)
@router.post("/items/{item_id}/buy")
async def buy_item(
    item_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: models.UserModel = Depends(get_current_user)
):
    # 核心防御：with_for_update() 强行施加行级排他锁
    # 这意味着在当前事务 commit 或 rollback 之前，没有任何其他请求能读取这行记录
    try:
        item = db.query(Item).filter(Item.id == item_id).with_for_update(nowait=True).first()
    except OperationalError:
        # nowait=True 使得拿不到锁的请求直接抛出异常，而不是死等。这叫“熔断”。
        raise HTTPException(status_code=409, detail="当前系统拥挤，抢购失败，请重试！")

    if not item:
        raise HTTPException(status_code=404, detail="该物品已在物理位面上消失。")
    if not item.is_offer:
        raise HTTPException(status_code=400, detail="求购贴拒绝执行抢购逻辑。")
    if item.is_sold:
        raise HTTPException(status_code=400, detail="晚了一步，商品已被截胡。")

    # 只有拿到唯一排他锁的那个线程，才能走到这里
    item.is_sold = True
    item.buyer_id = current_user.id
    
    # 事务提交，释放行锁
    db.commit()
    
    return {"message": "抢购成功！订单已锁定。"}

ai_client = ZhipuAI(
    api_key = "b40d93bc3d5748dd9fd47efdc32d0f0c.nhsV68wYizfmYx6v"
)
#支持上下文的pydantic模型
class Message(BaseModel):
    role: str
    content: str

class AgentRequest(BaseModel):
    history: Optional[List[Message]] = None
    messages: Optional[List[Message]] = None  # 支持标准的messages结构

# === 🌟 彻底删除之前的 tools 遗留代码，保持清爽 ===

# === 🌟 双子星 1号：记忆提取接口 (支持分页/上滑加载) ===
@router.get("/ai/history/")
async def get_ai_history(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db_session),
    current_user = Depends(get_current_user)
):
    """获取 AI 聊天历史接口 (支持分页)"""
    # 直接查询数据库，where 已经保证了数据隔离，不需要画蛇添足的 if 判断
    query = (
        select(models.AIChatRecord)
        .where(models.AIChatRecord.user_id == current_user.id)
        .order_by(desc(models.AIChatRecord.created_at))
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    records = result.scalars().all()
    
    # 查出来后把顺序倒回来，变成正常的聊天顺序
    records.reverse()
    
    return [{"role": r.role, "content": r.content, "timestamp": r.created_at.isoformat()} for r in records]


# === 🌟 双子星 2号：一键失忆接口 (DELETE) ===
# 🚨 确保这里的路径和 GET 一模一样，只是请求方法不同！
@router.delete("/ai/history/")
async def delete_ai_history(
    db: AsyncSession = Depends(get_db_session),
    current_user = Depends(get_current_user)
):
    print(f"🧹 [记忆管理] 收到用户 {current_user.username} 的专业级清除请求...")
    # 精准打击，只删当前登录用户的聊天记录
    await db.execute(delete(models.AIChatRecord).where(models.AIChatRecord.user_id == current_user.id))
    await db.commit()
    return {"message": "历史记忆已物理清除"}


# === 🌟 核心大脑：带物理外挂的 Agent ===
@router.post("/ai/agent")
async def agent_with_tools(
    request: AgentRequest, 
    db: AsyncSession = Depends(get_db_session),
    current_user = Depends(get_current_user)
):
    history_list = request.history or request.messages or []
    last_user_msg = history_list[-1].content if history_list else ""
    
    # 1. 💾 记忆写入 1：保存用户刚刚说的话
    # 1. 💾 存用户消息进数据库
    new_user_record = models.AIChatRecord(user_id=current_user.id, role="user", content=last_user_msg)
    db.add(new_user_record)
    await db.commit()

    # ===================================================
    # 🌟 架构师外挂升级：上下文感知检索 (Contextual RAG)
    # ===================================================
    # 提取上下文中所有用户的发言，以防止语义断层！
    user_history_texts = [
        msg.content if hasattr(msg, "content") else msg.get("content", "") if isinstance(msg, dict) else ""
        for msg in history_list 
        if (msg.role if hasattr(msg, "role") else msg.get("role", "") if isinstance(msg, dict) else "") == "user"
    ]
    
    # 🌟 核心魔法：使用最近的最多 3 条用户发言（滑动窗口），防止深层聊天时语义完全断层丢失上下文！
    recent_user_texts = user_history_texts[-3:]
    search_query = " ".join(recent_user_texts)

    print(f"🔫 [向量检索] 融合语境搜索词: '{search_query}'")
    try:
        embed_response = ai_client.embeddings.create(model="embedding-2", input=search_query)
        query_vector = embed_response.data[0].embedding

        query = (
            select(models.ItemModel)
            .where(models.ItemModel.is_offer == True)
            .where(models.ItemModel.inventory > 0) # 🌟 唯一真理：只要有库存，就允许卖！
            .where(models.ItemModel.embedding.is_not(None))
            .order_by(models.ItemModel.embedding.cosine_distance(query_vector))
            .limit(3)
        )
        result = await db.execute(query)
        items = list(result.scalars().all())
        
        # 🌟 强行补充传统文本包含匹配：因为如果有商品没有生成向量，向量检索就永远查不到！
        text_query = select(models.ItemModel).where(models.ItemModel.is_offer == True).where(models.ItemModel.inventory > 0)
        text_result = await db.execute(text_query)
        all_text_items = text_result.scalars().all()
        
        for item in all_text_items:
            # 如果商品名称里的连续2个字出现在用户询问中，强制纳入结果（非常粗暴有效的兜底）
            # 或者用户的长词出现在商品名中（如"相机" in "尼康相机"）
            match = False
            if len(search_query) >= 2:
                for i in range(len(search_query)-1):
                    bi_gram = search_query[i:i+2]
                    if len(bi_gram.strip()) == 2 and bi_gram in item.name:
                        match = True
                        break
            if match and item not in items:
                items.append(item)

        # 如果因为 Celery 没跑导致商品没有向量，或者算力偏差找不到，强行用传统 SQL 抓取最新商品！
        if not items:
            print("⚠️ [向量检索] 未命中任何带向量的商品，触发传统保底扫描...")
            # ❌ 同样在这里删掉 is_sold == False ！！
            backup_query = select(models.ItemModel).where(models.ItemModel.inventory > 0).limit(5)
            backup_result = await db.execute(backup_query)
            items = backup_result.scalars().all()
        db_data_str = "当前没有任何商品。" if not items else "、".join([f"ID:{item.id}-{item.name}(￥{item.price}, 剩余{item.inventory}件)" for item in items])
        print(f"🎯 [向量检索] 匹配成功！库存：{db_data_str}")
    except Exception as e:
        print(f"⚠️ [向量检索] 失败: {e}")
        db_data_str = "库存检索失败"

    # ===================================================
    # 🛡️ 架构师最终版状态机：加入售后护栏
    # ===================================================
    messages = [
        {
            "role": "system", 
            # 🌟 动态注入库存数据到 Prompt 模板中！
            "content": SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)
        }
    ]

    MAX_CONTEXT_MESSAGES = 6 
    if history_list:
        # 像切除肿瘤一样，只切取列表最末尾的 MAX_CONTEXT_MESSAGES 条记录
        recent_history = history_list[-MAX_CONTEXT_MESSAGES:]
        print(f"✂️ [上下文截断] 原始对话长度: {len(history_list)}，截断后保留: {len(recent_history)}")
        for msg in recent_history:
            role = getattr(msg, "role", "user") if hasattr(msg, "role") else msg.get("role", "user")
            content = getattr(msg, "content", "") if hasattr(msg, "content") else msg.get("content", "")
            messages.append({"role": role, "content": content})
    else:
        messages.append({"role": "user", "content": "你好"})

    # 4. 🛠️ 极其严格的 Tools 定义 (要求必须传 item_id)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_web_price",
                "description": "🚨【极度危险】当且仅当用户明确要求查看【外部市场价】、【全网比价】、【别人卖多少钱】时才允许调用！如果用户只是询问本平台有什么商品，绝对、绝对禁止调用此工具！",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "integer", "description": "必须提取的商品唯一ID（从提供的后台库存数据中获取）"},
                        "item_name": {"type": "string", "description": "要购买的商品名称"},
                        "address": {"type": "string", "description": "用户的详细收货地址"}
                    },
                    "required": ["item_id", "item_name", "address"]
                }
            }
        }
    ]

    # === 🌟 核心魔法：异步流式生成器 (将原本的逻辑包裹进来) ===
    async def generate_chat_stream():
        print("🤖 [Agent 核心] 开启水龙头！向带有 Tools 的云端大脑发送流式请求...")
        response = ai_client.chat.completions.create(
            model="glm-4.5-flash", 
            messages=messages,
            tools=tools,
            stream=True  # 👈 核心参数：开启流！
        )
        
        tool_call_name = ""
        tool_call_args = ""
        full_reply_text = ""

        # 🌟 滴水穿石：读取打字机输出
        for chunk in response:
            delta = chunk.choices[0].delta
            
            # 悄悄拦截工具调用的 JSON 字符串片段
            if delta.tool_calls:
                tc = delta.tool_calls[0]
                if tc.function.name: tool_call_name += tc.function.name
                if tc.function.arguments: tool_call_args += tc.function.arguments
                yield ":keep-alive\n\n"  # 给前端发送一个心跳包，保持连接不断开
            # 直接将正常的聊天文字喷射给前端
            elif delta.content:
                full_reply_text += delta.content
                yield f"data: {json.dumps({'content': delta.content})}\n\n"
        
        # ==========================================
        # 🌟 流接收完毕！在这里执行你的【绝对防御业务逻辑】
        # ==========================================
        # ==========================================
        # 🌟 流接收完毕！在这里执行你的【绝对防御业务逻辑】
        # ==========================================
        if tool_call_name == "create_order":
            print(f"⚡ [Function Calling] 拦截到完整参数: {tool_call_args}")
            args = json.loads(tool_call_args)
            
            try:
                item_id = int(args.get("item_id", 0))
            except ValueError:
                item_id = 0
            item_name = args.get("item_name", "未知商品")
            address = args.get("address", "") # 默认设为空
            
            # === 🌟 架构师的终极防骗拦截：没地址？滚回去问！ ===
            if not address or len(address) < 5 or address == "未知地址":
                print("❌ [安全拦截] AI 试图在没有地址的情况下发货，已打回！")
                refuse_msg = f"\n\n老板，您还没告诉我**详细的收货地址**呢！请把省市区街道等详细地址发我，我立刻给您下单【{item_name}】！"
                full_reply_text += refuse_msg
                yield f"data: {json.dumps({'content': refuse_msg})}\n\n"
            else:
                # === 地址正常，开始核实数据库 ===
                print(f"🛡️ [安全校验] 正在数据库核实 ID={item_id} 的真实存在与价格...")
                price_query = select(models.ItemModel).where(models.ItemModel.id == item_id).where(models.ItemModel.is_offer == True).where(models.ItemModel.is_sold == False)
                price_result = await db.execute(price_query)
                real_item = price_result.scalars().first()
                
                if not real_item:
                    fail_msg = f"\n\n抱歉老板，您想买的【{item_name}】刚才好像被别人抢先拍下，或者库存出现异常了。要不要看看别的？"
                    full_reply_text += fail_msg
                    yield f"data: {json.dumps({'content': fail_msg})}\n\n"
                else:
                    # 1. 安全扣减库存
                    if real_item.inventory > 0:
                        real_item.inventory -= 1
                        
                    # 只有库存真正归零时，才将状态锁死为售罄
                    if real_item.inventory == 0:
                        real_item.is_sold = True
                    
                    
                    try:
                        # 🌟 架构师修复：先 flush 将改动推到数据库但不提交事务
                        await db.flush()
                        
                        # 把消息投递给 Celery（如果有异常会直接在这里抛出）
                        send_feishu_alert_task.delay(real_item.name, real_item.price, current_user.email, address)
                        
                        # 确保投递成功后，再彻底提交数据库！
                        await db.commit()
                        
                        success_msg = f"\n\n🎉 搞定啦老板！您的【{real_item.name}】已经为您下单，我们马上安排发往：**{address}**！"
                        full_reply_text += success_msg
                        yield f"data: {json.dumps({'content': success_msg})}\n\n"
                    except Exception as e:
                        print(f"❌ [订单异常] {e}")
                        await db.rollback()
                        err_msg = "\n\n抱歉老板，系统刚打了个冷颤，订单没能写入成功，钱没扣，请稍后再试！"
                        full_reply_text += err_msg
                        yield f"data: {json.dumps({'content': err_msg})}\n\n"
        elif tool_call_name == "search_web_price":
            print(f"⚡ [Function Calling] AI 想要全网比价！参数: {tool_call_args}")
            args = json.loads(tool_call_args)
            item_name = args.get("item_name", "")
            
            if item_name:
                # 🌟 修复：先把字符串在外面拼好，避开 f-string 嵌套反斜杠的坑
                loading_msg = f"\n\n🕸️ 正在启动量子爬虫，潜入全网为老板搜索 **{item_name}** 的底价，请稍候..."
                yield f"data: {json.dumps({'content': loading_msg})}\n\n"
                
                # 🚀 召唤无头浏览器去抓取！
                market_data = await search_market_price(item_name)
                
                # 🌟 架构师 UI 魔法：向前端发送一个特殊的【结构化卡片标记】！
                # 提示 AI 总结一下数据，不要直接把乱码喷给用户
                summary_prompt = f"请用一两句话简短总结以下搜到的价格情报，告诉用户外面的价格是多少，并说一句我们平台的价格更香：\n{market_data}"
                
                print("🤖 [Agent] 正在让大模型总结情报...")
                summary_response = ai_client.chat.completions.create(
                    model="glm-4.5-flash",
                    messages=[{"role": "user", "content": summary_prompt}],
                    temperature=0.3
                )
                summary_text = summary_response.choices[0].message.content
                
                # 🌟 这里是重点：我们发送一个带有 specialType 的 JSON！
                card_data = {
                    "content": f"\n\n", # 换个行
                    "specialType": "price_card",
                    "itemName": item_name,
                    "marketPriceSummary": summary_text
                }
                yield f"data: {json.dumps(card_data)}\n\n"
                
                full_reply_text += f"\n[已展示 {item_name} 的全网价格卡片]\n{summary_text}"
        # 💾 无论发生了什么，最后将完整的句子存入数据库！
        new_ai_record = models.AIChatRecord(user_id=current_user.id, role="assistant", content=full_reply_text)
        db.add(new_ai_record)
        await db.commit()
        
        # 宣告本次流式连接彻底结束
        yield "data: [DONE]\n\n"

    # 将上面打包好的水龙头，返回给 FastAPI 的引擎
    return StreamingResponse(generate_chat_stream(), media_type="text/event-stream")

## === 🌟 个人中心：数据看板聚合接口 ===
@router.get("/dashboard/me")
async def get_my_dashboard(
    db: AsyncSession = Depends(get_db_session),
    current_user = Depends(get_current_user)
):
    #"""获取当前用户的所有核心数据（发布的商品、历史订单等）"""
    
    # 1. 查我发布的商品 (按最新发布排序)
    my_items_query = (
        select(models.ItemModel)
        .where(models.ItemModel.owner_id == current_user.id)
        .order_by(desc(models.ItemModel.id))
    )
    my_items = (await db.execute(my_items_query)).scalars().all()
    # 2. 查我买到的订单 (连表查出具体买了啥商品)
    # 🌟 核心魔法：selectinload 提前把订单对应的商品信息打包查出来，防止异步报错！
    my_orders_query = (
        select(models.OrderModel)
        .options(selectinload(models.OrderModel.item))  # 预加载订单对应的商品信息
        .where(models.OrderModel.buyer_id == current_user.id)
        .order_by(desc(models.OrderModel.id))
    )
    my_orders = (await db.execute(my_orders_query)).scalars().all()
    # 3. 组装看板数据，一次性发给前端！
    return {
        "user_email": current_user.email,
        "stats": {
            "published_count": len(my_items),
            "orders_count": len(my_orders)
        },
        "my_items": [{"id": i.id, "name": i.name, "price": i.price, "is_sold": i.is_sold} for i in my_items],
        "my_orders": [
            {
                "order_id": o.id, 
                "item_name": o.item.name if o.item else "商品已下架", 
                "price": o.item.price if o.item else 0,
                "status": o.status, 
                "time": o.created_at.isoformat()
            } for o in my_orders
        ]
    }