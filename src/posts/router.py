#处理http请求
import os
import asyncio
import shutil
from fastapi import APIRouter, Depends, Query, HTTPException,File, UploadFile, Form,BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
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
from sqlalchemy import select,func
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

# === 🌟 AI Agent 阶段 2：赋予寻找商品的双手 ===

tools = [
    {
        "type": "function",
        "function": {
            "name": "search_items",
            "description": "根据关键词查询平台上的商品（包括出售和求购）",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜索关键词，如果不提供则返回所有商品"
                    }
                },
                "required": []
            }
        }
    }
]

@router.post("/ai/agent")
async def agent_with_tools(request: AgentRequest, db: AsyncSession = Depends(get_db_session)):
    print(f"\n🧠 [Agent 核心] 收到包含 {len(request.history or request.messages or [])} 条记忆的对话请求")
    
    # 1. 组装上下文：System Prompt 洗脑包 + 前端传来的全部历史记录
    system_msg = {"role": "system", "content": "你是闲小宝，一个二手交易平台的 AI 管家。如果有需要，请善用你的工具来回答用户问题。"}
    messages = [system_msg]
    for msg in (request.history or request.messages or []):
        messages.append({"role": msg.role, "content": msg.content})

    if len(messages) == 1:
        messages.append({"role": "user", "content": "你好，我是用户"})
    print("🚀 [Agent] 发送至智谱的 messages =", messages)
    
    # 2. 带着完整的记忆去问 AI
    response = ai_client.chat.completions.create(
        model="glm-4.5-flash",
        messages=messages,
        tools=tools,
        temperature=0.7
    )
    
    choice = response.choices[0]
    
    # 3. 处理工具调用（跟之前一样）
    if choice.message.tool_calls:
        tool_call = choice.message.tool_calls[0]
        print(f"🔧 [Agent 核心] AI 决定使用工具: {tool_call.function.name}")
        
        if tool_call.function.name == "get_available_items":
            query = select(models.ItemModel).where(models.ItemModel.is_offer == True)
            result = await db.execute(query)
            items = result.scalars().all()
            
            db_data_str = "当前平台没有任何在售商品。" if not items else "、".join([f"{item.name}(￥{item.price})" for item in items])
            
            # ✅ 架构师解药：手动提取干净的参数，剥离 OpenAI 的多余字段
            # 1. 组装 AI 的请求动作
            assistant_message = {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                ]
            }
            # ⚠️ 核心魔法：只有当 AI 真的说了废话时，我们才加上 content 字段！
            # 绝对不能传 "" 或者 None 给智谱！
            if choice.message.content:
                assistant_message["content"] = choice.message.content
                
            messages.append(assistant_message)
            
            # 2. 组装数据库的查询结果
            messages.append({
                "role": "tool",
                "content": str(db_data_str), # 确保这里绝对是字符串
                "tool_call_id": tool_call.id
            })
            
            final_response = ai_client.chat.completions.create(
                model="glm-4.5-flash",
                messages=messages
            )
            return {"reply": final_response.choices[0].message.content}
            
    # 如果没调用工具，直接返回
    return {"reply": choice.message.content}
        
        