
import os
import asyncio
import shutil
from fastapi import APIRouter, Depends, Query, HTTPException,File, UploadFile, Form,BackgroundTasks,status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
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
router = APIRouter(
    prefix="/items",
    tags=["items"]
)

redis_client = aioredis.Redis(host='redis', port=6379, db=0, decode_responses=True)

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
    """创建接口：使用 JSON `ItemCreate` 模型（图片需先上传获取路径）"""
    # 调用 service，传入 current_user.id 作为 owner_id
    db_item = await service.create_item(db=db, item=item, owner_id=current_user.id)

    # 把 AI 审核任务交给后台去做，主线程不等它，直接返回响应
    if item.image_path:
        background_tasks.add_task(ai_image_review, filename=item.image_path)
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

    #1.构造一个查询图纸
    query = select(models.ItemModel)
    # 🌟 新增：永远只查出没有被卖掉的商品！
    query = query.where(models.ItemModel.is_sold == False)
    if is_offer_filter is not None:
        query = query.where(models.ItemModel.is_offer == is_offer_filter)
    if search:
        query = query.where(models.ItemModel.name.ilike(f"%{search}%"))

    """查询物品列表"""
    # 动态构建查询
    count_query = select(func.count()).select_from(query.subquery())  # 先构造一个子查询来计算总数
    total = await db.scalar(count_query)
    
    #3.切割数据
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "total": total,
        "items": items
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
    """安全下单接口 (带防超卖悲观锁)"""
    # 1. 先把物品查出来，并且加上悲观锁（FOR UPDATE）
    query = select(models.ItemModel).where(models.ItemModel.id == item_id).with_for_update()
    result = await db.execute(query)
    item = result.scalars().first()
    
    if not item:
        raise HTTPException(status_code=404, detail="商品不存在")
    
    if item.is_sold:
        raise HTTPException(status_code=400, detail="手慢了，该宝贝已被抢购一空！")

    #不能购买自己发布的商品
    if item.owner_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能购买自己发布的商品！")

    # 4. 拦截器：求购贴不能“被购买”
    if not item.is_offer:
        raise HTTPException(status_code=400, detail="这是求购贴，不能被购买！")
    
    try:
        # ✅ 所有检查通过，开始“一手交钱，一手交货”
        
        # 将商品标记为已售出
        item.is_sold = True
        
        # 生成真实订单 (这里为了极速体验，我们直接将状态设为 'paid' 已付款)
        new_order = models.OrderModel(
            item_id=item_id,
            buyer_id=current_user.id,
            status="paid" 
        )
        db.add(new_order)
        
        # 提交事务：订单生成和商品状态更新同时生效，然后释放那把“悲观锁”
        await db.commit()
        
        return {
            "message": "🎉 恭喜你，抢购成功！", 
            "order_id": new_order.id,
            "item_name": item.name
        }
        
    except Exception as e:
        # 如果中间发生任何意外，数据回滚，坚决不产生脏数据！
        await db.rollback()
        raise HTTPException(status_code=500, detail="服务器开小差了，购买失败！")

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
    current_user = Depends(get_current_user) # 🌟 核心：知道是谁在聊天！
):
    history_list = request.history or request.messages or []
    last_user_msg = history_list[-1].content if history_list else ""
    print(f"\n🧠 [Agent 核心] 收到用户 {current_user.username} 的最新指令: {last_user_msg}")

    # ===================================================
    # 💾 记忆写入 1：保存用户刚刚说的话
    # ===================================================
    new_user_record = models.AIChatRecord(
        user_id=current_user.id, role="user", content=last_user_msg
    )
    db.add(new_user_record)
    await db.commit() # 存入硬盘！

    # === 🌟 架构师外挂：穷人版意图拦截器 (RAG 架构) ===
    trigger_words = ["什么", "卖", "买", "多少钱", "价格", "有", "卡", "电脑", "手机", "二手", "查"]
    need_db_search = any(word in last_user_msg for word in trigger_words)
    
    messages = [
        {"role": "system", "content": "你是闲小宝，一个二手交易平台的AI管家。说话幽默风趣。如果系统给你提供了数据，请直接根据数据回答，不要客套。"}
    ]
    
    if need_db_search:
        print("🔫 [物理外挂] 命中关键词！直接用 Python 查数据库！")
        query = select(models.ItemModel).where(models.ItemModel.is_offer == True)
        result = await db.execute(query)
        items = result.scalars().all()
        db_data_str = "当前没有任何商品。" if not items else "、".join([f"{item.name}(￥{item.price})" for item in items])
        messages.append({
            "role": "system", 
            "content": f"【后台自动查询结果】：目前平台有以下商品：{db_data_str}。请直接用这段数据回答用户刚才的问题！"
        })
    # ==================================

    # 拼装用户的聊天记录
    for msg in history_list:
        messages.append({"role": msg.role, "content": msg.content})

    if len(history_list) == 0:
        messages.append({"role": "user", "content": "你好"})

    print("🤖 [Agent 核心] 正在向云端大脑发送最终请求...")
    response = ai_client.chat.completions.create(
        model="glm-4.5-flash", 
        messages=messages,
        max_tokens=4096,
        temperature=0.4 
    )
    
    reply = response.choices[0].message.content
    print(f"✅ [Agent 核心] 最终回复: {reply}")
    
    # ===================================================
    # 💾 记忆写入 2：保存 AI 的回复
    # ===================================================
    new_ai_record = models.AIChatRecord(
        user_id=current_user.id, role="assistant", content=reply
    )
    db.add(new_ai_record)
    await db.commit() # 再次存入硬盘！
    
    return {"reply": reply}

## === 🌟 个人中心：数据看板聚合接口 ===
@router.get("/dashboard/")
async def user_dashboard(
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