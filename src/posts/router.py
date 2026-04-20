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
from src.auth.dependencies import get_current_user, get_current_user_optional
from src.feishu.router import send_feishu_message
from src.database import AsyncSessionLocal
from src.posts import service as posts_service
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
from fastapi.responses import StreamingResponse
from src.worker import inject_embedding_task,send_feishu_alert_task
from src.auth.dependencies import get_admin_user
from .prompts import SALES_AGENT_SYSTEM_PROMPT
from src.posts.agent_graph import graph
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from src.posts.ai_vision import get_image_embedding
router = APIRouter(
    prefix="/items",
    tags=["items"]
)

import os
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
redis_client = aioredis.Redis(host=REDIS_HOST, port=6379, db=0, decode_responses=True)
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

from src.posts.ai_vision import get_image_embedding
import io

@router.post("/upload-image/")
async def upload_image(
    file: UploadFile = File(...)
):
    image_bytes = await file.read()
    try:
        # ai_vision.py 中的 get_image_embedding 是普通同步函数，不要用 await
        img_vector = get_image_embedding(image_bytes)
        print(f"📊 [AI 视觉] 成功提取图片特征向量，长度: {len(img_vector)}")
    except Exception as e:
        print(f"🚨 [AI 视觉] 图片特征提取失败: {e}")
        img_vector = None

    # 让 subsequent current_storage.upload(file) 可以起作用
    file.file.seek(0)
    
    """专门的图片上传接口 (现在通过统一 Storage 策略处理)"""
    
    # 🌟 核心：把文件直接丢给大管家，不用管它是存本地还是存云端！
    image_url = await current_storage.upload(file)
    
    # 依然保留后台处理任务
    background_tasks.add_task(process_image_in_background, filename=file.filename)
    
    return {
        "filename": file.filename, 
        "url": image_url,  # 🌟 直接返回管家给的网址
        "image_embedding": img_vector, # 返回前台并在发布商品时携带
        "message": "图片上传成功，特征提取完成！"
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
@router.post("/{item_id}/buy")
async def buy_item(
    item_id: int,
    db: AsyncSession = Depends(get_db_session),
    current_user: models.UserModel = Depends(get_current_user)
):
    # 1. 核心防御：with_for_update() 强行施加行级排他锁
    try:
        result = await db.execute(
            select(models.ItemModel)
            .where(models.ItemModel.id == item_id)
            .with_for_update(nowait=True)
        )
        item = result.scalars().first()
    except OperationalError:
        # nowait=True 使得拿不到锁的请求直接抛出异常，而不是死等。这叫“熔断”。
        raise HTTPException(status_code=409, detail="当前系统拥挤，抢购失败，请重试！")

    # 2. 各种前置校验
    if not item:
        raise HTTPException(status_code=404, detail="该物品已在物理位面上消失。")
    if not item.is_offer:
        raise HTTPException(status_code=400, detail="求购贴拒绝执行抢购逻辑。")
    if item.is_sold or item.inventory <= 0:
        raise HTTPException(status_code=400, detail="晚了一步，商品已售罄。")

    # 3. 🌟 修复库存逻辑：精准扣减
    item.inventory -= 1
    
    # 只有当库存真的被扣到 0 的时候，才打上售罄标签！
    if item.inventory == 0:
        item.is_sold = True
    
    # 为了兼容之前的单品逻辑，保留 buyer_id
    item.buyer_id = current_user.id

    # 4. 🌟 修复订单逻辑：生成真实的交易流水 (OrderModel)
    # 这样你的 Dashboard 里的“最新订单记录”才会真正长出数据！
    new_order = models.OrderModel(
        item_id=item.id,
        buyer_id=current_user.id,
        status="paid"  # 假设直接付款成功
    )
    db.add(new_order)
    
    # 5. 提交事务，释放行锁
    await db.commit()
    
    # ==========================================
    # 🚀 [可选扩展] 触发异步飞书通知（后台发送，不阻塞前端抢购）
    # 如果你想让卖家瞬间收到爆单通知，可以解开这行注释：
    # send_feishu_alert_task.delay(f"🎉 爆单啦！您发布的商品【{item.name}】刚刚被买走了一件！剩余库存：{item.inventory}")
    # ==========================================
    
    return {"message": f"抢购成功！订单已锁定，该商品还剩 {item.inventory} 件库存。"}

#支持上下文的pydantic模型
class Message(BaseModel):
    role: str = "user"
    content: str = ""

class AgentRequest(BaseModel):
    history: Optional[List[Message]] = None
    messages: Optional[List[Message]] = None  # 支持标准的messages结构
    content: Optional[str] = None  # 兼容旧版前端只传一条文本
    message: Optional[str] = None  # 兼容 message 字段

# === 🌟 彻底删除之前的 tools 遗留代码，保持清爽 ===

# === 🌟 双子星 1号：记忆提取接口 (支持分页/上滑加载) ===
@router.get("/ai/history/")
async def get_ai_history(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db_session),
    current_user = Depends(get_current_user_optional)
):
    """获取 AI 聊天历史接口 (支持分页)"""
    if current_user is None:
        # 前端首次加载/Token 失效时，平滑返回空历史，避免401刷屏
        return []

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
    if not history_list:
        single_text = (request.content or request.message or "").strip()
        if single_text:
            history_list = [Message(role="user", content=single_text)]

    if not history_list:
        raise HTTPException(status_code=422, detail="请提供 history/messages，或 content/message 文本")

    last_user_msg = history_list[-1].content if history_list else ""

    # 1. 💾 保存用户提问
    new_user_record = models.AIChatRecord(user_id=current_user.id, role="user", content=last_user_msg)
    db.add(new_user_record)
    await db.commit()

    # 2. 组装极简系统提示，数据库检索交给 LangGraph 自主工具
    system_prompt = (
        "你叫闲小宝，是二手交易平台的金牌导购兼客服。"
        "你的职责是：帮用户找商品、全网比价、帮用户下单。"
        "当用户找商品时，必须调用 search_platform_products 工具查询真实库存，禁止编造。"
        "禁止输出任何内部执行过程、工具调用状态、系统节点信息或思考过程。"
        "禁止出现如 [LangGraph]、正在思考、工具触发、爬虫启动、请稍候 等过程话术。"
        "问规则（如退换货/防骗）必须调用 search_platform_policy 工具去翻阅知识库。"
        "当你需要了解当前市场外面的价格，或者用户问了非平台内的问题时，请【主动使用你的自带联网搜索技能 (web_search)】，去全网收集最新信息后回答用户！"
        "绝对不能把找商品和查规则的工具用混了！"
    )

    messages = [SystemMessage(content=system_prompt)]

    max_context_messages = 6
    recent_history = history_list[-max_context_messages:] if history_list else []
    if recent_history:
        print(f"✂️ [上下文截断] 原始对话长度: {len(history_list)}，截断后保留: {len(recent_history)}")
        for msg in recent_history:
            role = getattr(msg, "role", "user") if hasattr(msg, "role") else msg.get("role", "user")
            content = getattr(msg, "content", "") if hasattr(msg, "content") else msg.get("content", "")
            if role == "assistant":
                messages.append(AIMessage(content=content))
            else:
                messages.append(HumanMessage(content=content))
    else:
        messages.append(HumanMessage(content="你好"))

    # 3. LangGraph 流式执行
    async def generate_chat_stream():
        try:
            print("🤖 [Agent 核心] 开启 LangGraph 流式请求...")
            full_reply_text = ""
            suppress_internal_line = False

            hidden_markers = [
                "[langgraph]",
                "正在启动量子爬虫",
                "量子爬虫",
                "全网比价，请稍候",
                "请稍候",
                "正在思考",
                "tool 触发",
                "工具触发",
                "节点",
                "内部执行",
            ]
            stop_tokens = ["\n", "。", "！", "!", "？", "?"]
            recent_window = ""

            async for msg, metadata in graph.astream(
                {"messages": messages},
                stream_mode="messages"
            ):
                node_name = metadata.get("langgraph_node", "") if metadata else ""

                if node_name == "tools":
                    tool_name = getattr(msg, "name", "")
                    if tool_name == "search_platform_products":
                        # 对平台库存检索工具保持静默，不向前端暴露内部执行提示
                        pass
                    elif tool_name == "create_order":
                        # 对下单工具保持静默，避免暴露内部执行过程
                        pass
                    continue

                # 只把 chatbot 节点产出的 AI 文本推给前端，避免 system/human/tool 消息泄露
                msg_type = str(getattr(msg, "type", "")).lower()
                msg_cls = msg.__class__.__name__
                is_ai_msg = msg_type in {"ai", "aimessagechunk"} or msg_cls in {"AIMessage", "AIMessageChunk"}
                if node_name != "chatbot" or not is_ai_msg:
                    continue

                content = getattr(msg, "content", "")
                if isinstance(content, list):
                    text = "".join(
                        block.get("text", "") for block in content
                        if isinstance(block, dict) and block.get("type") == "text"
                    )
                else:
                    text = str(content or "")

                if text:
                    lowered = text.lower()
                    mixed_window = (recent_window + lowered)[-240:]

                    if suppress_internal_line or any(marker in mixed_window for marker in hidden_markers):
                        if any(token in text for token in stop_tokens):
                            suppress_internal_line = False
                        else:
                            suppress_internal_line = True
                        recent_window = mixed_window[-120:]
                        continue

                    recent_window = mixed_window[-120:]

                    full_reply_text += text
                    yield f"data: {json.dumps({'content': text})}\n\n"

            # 💾 保存 AI 最终回复
            new_ai_record = models.AIChatRecord(user_id=current_user.id, role="assistant", content=full_reply_text)
            db.add(new_ai_record)
            await db.commit()

            yield "data: [DONE]\n\n"
        except Exception as e:
            import traceback; traceback.print_exc()
            err_msg = f"\n\n🚨 [系统提示] AI思考时发生异常或网络中断，原因是: {str(e)}"
            yield f"data: {json.dumps({'content': err_msg})}\n\n"
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

async def process_feishu_message(event_data: dict):
    try:
        message = event_data.get("message", {})
        msg_type = message.get("message_type")
        content_str = message.get("content", "{}")
        
        if msg_type != "text":
            return

        content_dict = json.loads(content_str)
        user_text = content_dict.get("text", "")
        sender_id = event_data.get("sender", {}).get("sender_id", {}).get("open_id", "unknown")
        
        print(f"🤖 [后台接管] 收到用户 {sender_id} 的消息: '{user_text}'")

        # ==========================================
        # 🛡️ 灵魂拦截器：后台任务自己拿钥匙开门查数据库
        # ==========================================
        async with AsyncSessionLocal() as db:
            # 1. 查户口 (调用你刚才写的技能 1)
            current_user = await posts_service.get_user_by_feishu_id(db, sender_id)
            
            if not current_user:
                # ❌ 场景 A：查无此人，拦截并发送绑定链接！
                # 注意：这里的链接先写死一个本地前端地址，后续你做前端了再替换
                bind_url = f"http://localhost:5173/bind-feishu?open_id={sender_id}"
                
                reply_text = f"老板你好！我是闲小宝。系统发现您还没绑定咱们的平台账号呢。\n请点击这里完成绑定：{bind_url}\n绑定后我才能帮您呼叫 AI 查订单哦！"
                await send_feishu_message(sender_id, reply_text)
                
                print(f"🚧 访客 {sender_id} 未绑定，已拦截并发送链接。")
                return  # 直接 return，绝对不让他去消耗 AI 大脑！

            # ✅ 场景 B：查到了！是尊贵的业主！
            print(f"✅ 身份确认：飞书用户 {sender_id} 是我们尊贵的业主：{current_user.username}")
            
            # ==========================================
            # 🌟 1. 飞书服务员先去档案室调取用户的历史记忆
            # ==========================================
            from sqlalchemy import select, desc # 确保能用到倒序排列
            
            history_query = (
                select(models.AIChatRecord)
                .where(models.AIChatRecord.user_id == current_user.id)
                .order_by(desc(models.AIChatRecord.created_at))
                .limit(6) # 拿最近的 6 条对话作为记忆
            )
            history_result = await db.execute(history_query)
            history_list = history_result.scalars().all()
            history_list.reverse() # 倒转成正常的聊天先后顺序
            
            print(f"📚 [飞书岗亭] 成功提取到 {len(history_list)} 条历史记忆！")

            # ==========================================
            # 🌟 2. 拿着记忆和问题，去中央厨房接菜！
            # ==========================================
            full_reply = ""
            
            # 🚨 注意看：这里把 history_list 传给了中央厨房的大厨！
            async for chunk in posts_service.ask_ai_agent(db, current_user, user_text, history_list=history_list):
                if chunk["type"] == "text":
                    full_reply += chunk["content"]
                elif chunk["type"] == "card":
                    # 将网页端华丽的价格卡片，降维翻译成飞书能看懂的文字段落
                    full_reply += f"\n\n📊【全网底价情报】\n商品：{chunk['item_name']}\n结论：{chunk['marketPriceSummary']}"
            
            print(f"✅ [飞书岗亭] 菜做好了，准备端出！回复长度：{len(full_reply)}")
            
            # 3. 菜全部装好，一锅端给用户！
            await send_feishu_message(sender_id, full_reply)

    except Exception as e:
        print(f"❌ [后台接管] 处理飞书消息时崩溃: {e}")

# =========================================
# 👑 管理员核禁区：测试接口
# ==========================================
@router.get("/admin/secret-base")
async def get_secret_base(
    admin_user: models.UserModel = Depends(get_admin_user)
):
    """只有管理员能访问的秘密基地接口"""
    return {
        "message": f"👑 欢迎陛下！尊贵的管理员 {admin_user.email}，这是只有您能看到的机密！",
        "action": "您可以尽情下架任何人的商品啦！"
    }

# ==========================================
# 🆕 全能注册接口 (支持买家/卖家身份选择)
# ==========================================
@router.post("/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(
    user: schemas.UserCreate, 
    db: AsyncSession = Depends(get_db_session)
):
    # 1. 🛡️ 防御检查 1：邮箱是否被占用？
    existing_user = await service.get_user_by_email(db, user.email)
    if existing_user:
        raise HTTPException(status_code=400, detail="手慢了，该邮箱已被注册！")
    
    # 2. 🛡️ 防御检查 2：防止黑客乱传角色（比如传了个 'super_hacker'）
    if user.role not in ["user", "admin"]:
        raise HTTPException(status_code=400, detail="非法的角色类型！只能注册为 user(买家) 或 admin(卖家)")

    # 3. 🚀 放行，写入数据库！
    new_user = await service.create_user(db, user)
    
    print(f"🎉 [新用户注册] 邮箱: {new_user.email}, 身份: {new_user.role}")
    return new_user