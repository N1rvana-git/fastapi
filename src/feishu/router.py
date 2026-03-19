import httpx
import json
import asyncio
from pydantic import BaseModel
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from zhipuai import ZhipuAI
import redis.asyncio as aioredis
from sqlalchemy import select, desc, delete
from src.posts.prompts import SALES_AGENT_SYSTEM_PROMPT
from src.posts.scraper import search_market_price
from src.worker import send_feishu_alert_task

from sqlalchemy import select, desc, delete
from src.posts.prompts import SALES_AGENT_SYSTEM_PROMPT
from src.posts.scraper import search_market_price
from src.worker import send_feishu_alert_task


# 引入数据库工厂和 user service
from src.database import AsyncSessionLocal
from src.posts import service as posts_service 
from src.auth.dependencies import get_current_user
from src.posts.dependencies import get_db_session
from src.posts import models
from src.posts import service as posts_services
router = APIRouter(prefix="/feishu", tags=["Feishu"])
redis_client = aioredis.Redis(host='redis', port=6379, db=0, decode_responses=True)
class BindFeishuRequest(BaseModel):
    open_id: str

# ==========================================
# 🔗 登记处：飞书账号绑定接口
# ==========================================
@router.post("/bind")
async def bind_feishu_account(
    request: BindFeishuRequest,
    db: AsyncSessionLocal = Depends(get_db_session), 
    current_user: models.UserModel = Depends(get_current_user)):
    print(f"🔗 [绑定登记处] 用户 {current_user.username} 请求绑定飞书账号 {request.open_id}")

    # 1. 安全校验：检查这个飞书号是不是已经被别人绑过了？
    existing_user = await posts_services.get_user_by_feishu_id(db, request.open_id)
    if existing_user:
        if existing_user.id == current_user.id:
            return {"message": "这个飞书账号已经绑定在你名下了，无需重复绑定！"}
        else:
            return {"error": "这个飞书账号已经被其他用户绑定了，请联系管理员！"}

    await posts_services.bind_feishu_account(db, current_user.id, request.open_id)
    print(f"✅ [绑定登记处] 用户 {current_user.username} 成功绑定飞书账号 {request.open_id}")

# ==========================================
# 🔐 飞书应用配置 (请替换为你自己的真实数据)
# ==========================================
FEISHU_VERIFICATION_TOKEN = "B0Nfx7Vc3kJ8656yvICRjhZu1dWePdMV"  # 👈 填入你的 Verification Token
FEISHU_APP_ID = "cli_a93906ec7dfa1bc0"
FEISHU_APP_SECRET = "Oaytk9gpKydsabBmPod0Tb7XMcMlUfde"


# ==========================================
# 🧠 核心：异步处理大脑 (突破 3 秒限制)
# ==========================================
async def send_feishu_message(open_id: str, text: str):
    """主动调用飞书 API，给指定用户发送文本消息"""
    async with httpx.AsyncClient() as client:
        # 1. 换取临时通行证 (Token)
        token_url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        token_res = await client.post(token_url, json={
            "app_id": FEISHU_APP_ID,
            "app_secret": FEISHU_APP_SECRET
        })
        token = token_res.json().get("tenant_access_token")
        
        if not token:
            print("❌ [飞书发信] 获取 Token 失败，请检查 APP_ID 和 SECRET！")
            return

        # 2. 发送消息
        msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id"
        msg_res = await client.post(
            msg_url,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "receive_id": open_id,
                "msg_type": "text",
                "content": json.dumps({"text": text})
            }
        )
        print(f"✅ [飞书发信] 消息已发送给 {open_id}，飞书返回: {msg_res.json().get('msg')}")

# ==========================================
# 🧠 核心：后台处理大脑
# ==========================================
ai_client = ZhipuAI(api_key="b40d93bc3d5748dd9fd47efdc32d0f0c.nhsV68wYizfmYx6v")

async def process_feishu_message(event_data: dict):
    try:
        # 提取用户发来的消息内容
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
        # 🛑 智能闸机：Redis 分布式高并发限流
        # ==========================================
        if sender_id != "unknown":
            # 1. 制作每个用户专属的“计次卡”名字
            rate_limit_key = f"feishu:rate_limit:{sender_id}"
            
            try:
                # 2. Redis 原子操作：在卡上打孔 (+1)
                current_count = await redis_client.incr(rate_limit_key)
            except Exception as e:
                print(f"⚠️ Redis连接失败，跳过防爆盾机制: {e}")
                current_count = 1  # 降级处理，允许通过
                
            
            # 3. 如果是第一次打孔，给这张卡设定一个 60 秒后自动销毁的定时炸弹！
            if current_count == 1:
                try:
                    await redis_client.expire(rate_limit_key, 60)
                except Exception:
                    pass
                
            # 4. 保安核心逻辑：检查打孔次数
            if current_count > 3:
                print(f"🛑 [防爆盾触发] 飞书用户 {sender_id} 呼叫过于频繁 (一分钟内第 {current_count} 次)！已强行拦截！")
                
                # 温柔地提示用户被限流了
                await send_feishu_message(sender_id, "🛑 老板，我脑子转冒烟了！您的手速太快了，请休息一分钟再接着聊吧！🥵")
                
                # 🌟 极其关键的一步：直接 return！
                # 绝对不允许代码继续往下走，保护数据库和大模型！
                return 
        # ==========================================

        # ==========================================
        # 🛡️ 灵魂拦截器：后台任务自己拿钥匙开门查数据库
        # ==========================================
        async with AsyncSessionLocal() as db:
            # 1. 查户口
            current_user = await posts_service.get_user_by_feishu_id(db, sender_id)
            
            if not current_user:
                # ❌ 场景 A：查无此人，拦截并发送绑定链接！
                bind_url = f"http://localhost:5173/bind-feishu?open_id={sender_id}"
                
                reply_text = f"老板你好！我是闲小宝。系统发现您还没绑定咱们的平台账号呢。\n请点击这里完成绑定：{bind_url}\n绑定后我才能帮您呼叫 AI 查订单哦！"
                await send_feishu_message(sender_id, reply_text)
                
                print(f"🚧 访客 {sender_id} 未绑定，已拦截并发送链接。")
                return  # 直接 return，绝对不让他去消耗 AI 大脑！

            # ✅ 场景 B：查到了！是尊贵的业主！
            print(f"✅ 身份确认：飞书用户 {sender_id} 是我们尊贵的业主：{current_user.username}")

            if user_text.strip() == "/del texts":
                delete_stmt = delete(models.AIChatRecord).where(models.AIChatRecord.user_id == current_user.id)
                await db.execute(delete_stmt)
                await db.commit()
                await send_feishu_message(sender_id, "✅ 您的历史聊天记录已成功清除！我们可以重新开始聊天啦。")
                print(f"🧹 已清空这名用户({current_user.username})的聊天记录")
                return

            # 1. 💾 记忆写入 1：保存用户刚刚说的话
            new_user_record = models.AIChatRecord(user_id=current_user.id, role="user", content=user_text)
            db.add(new_user_record)
            await db.commit()

            # 获取历史记录
            history_query = (
                select(models.AIChatRecord)
                .where(models.AIChatRecord.user_id == current_user.id)
                .order_by(desc(models.AIChatRecord.created_at))
                .limit(6)
            )
            history_result = await db.execute(history_query)
            history_records = list(history_result.scalars().all())
            history_records.reverse()

            user_history_texts = [r.content for r in history_records if r.role == 'user']
            recent_user_texts = user_history_texts[-3:] if user_history_texts else [user_text]
            search_query = " ".join(recent_user_texts)

            print(f"🔫 [向量检索] 融合语境搜索词: '{search_query}'")
            try:
                embed_response = await asyncio.to_thread(
                    ai_client.embeddings.create,
                    model="embedding-2", 
                    input=search_query
                )
                query_vector = embed_response.data[0].embedding

                query = (
                    select(models.ItemModel)
                    .where(models.ItemModel.is_offer == True)
                    .where(models.ItemModel.inventory > 0)
                    .where(models.ItemModel.embedding.is_not(None))
                    .order_by(models.ItemModel.embedding.cosine_distance(query_vector))
                    .limit(3)
                )
                result = await db.execute(query)
                items = list(result.scalars().all())
                
                text_query = select(models.ItemModel).where(models.ItemModel.is_offer == True).where(models.ItemModel.inventory > 0)
                text_result = await db.execute(text_query)
                all_text_items = text_result.scalars().all()
                
                for item in all_text_items:
                    match = False
                    if len(search_query) >= 2:
                        for i in range(len(search_query)-1):
                            bi_gram = search_query[i:i+2]
                            if len(bi_gram.strip()) == 2 and bi_gram in item.name:
                                match = True
                                break
                    if match and item not in items:
                        items.append(item)

                if not items:
                    backup_query = select(models.ItemModel).where(models.ItemModel.inventory > 0).limit(5)
                    backup_result = await db.execute(backup_query)
                    items = backup_result.scalars().all()
                db_data_str = "当前没有任何商品。" if not items else "、".join([f"ID:{item.id}-{item.name}(￥{item.price}, 剩余{item.inventory}件)" for item in items])
            except Exception as e:
                print(f"⚠️ [向量检索] 失败: {e}")
                db_data_str = "库存检索失败"

            messages = [
                {
                    "role": "system", 
                    "content": f"你也是闲小宝飞书分机，保持和网页端一致的人设。面对你的老板{current_user.username}。\n\n" + SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)
                }
            ]

            for msg in history_records:
                messages.append({"role": msg.role, "content": msg.content})

            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "search_web_price",
                        "description": "🚨【极度危险】当且仅当用户明确要求查看【外部市场价】、【全网比价】、【别人卖多少钱】时才允许调用！如果用户只是询问本平台有什么商品，绝对、绝对禁止调用此工具！",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "item_name": {"type": "string", "description": "要查询或比价的商品名称关键字（如：哈苏X2D、Sony微单等）"}
                            },
                            "required": ["item_name"]
                        }
                    }
                },
                {
                    "type": "function",
                    "function": {
                        "name": "create_order",
                        "description": "用户说['我要了', '怎么买', '老地址']，在取得详细地址后调用以扣库存和发飞书提醒",
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

            print("🤖 [Agent] 正在思考...")
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model="glm-4.5-flash",
                messages=messages,
                tools=tools,
            )
            
            message_obj = response.choices[0].message
            reply_text = ""
            
            if hasattr(message_obj, 'tool_calls') and message_obj.tool_calls:
                tool_call = message_obj.tool_calls[0]
                tool_call_name = tool_call.function.name
                tool_call_args = json.loads(tool_call.function.arguments)
                
                print(f"⚡ [Function Calling] AI 选择工具: {tool_call_name}, 参数: {tool_call_args}")
                
                if tool_call_name == "create_order":
                    item_id = int(tool_call_args.get("item_id", 0))
                    item_name = tool_call_args.get("item_name", "未知商品")
                    address = tool_call_args.get("address", "")
                    
                    if not address or len(address) < 5 or address == "未知地址":
                        reply_text = f"老板，您还没告诉我**详细的收货地址**呢！请把省市区街道等详细地址发我，我立刻给您下单【{item_name}】！"
                    else:
                        price_query = select(models.ItemModel).where(models.ItemModel.id == item_id).where(models.ItemModel.is_offer == True).where(models.ItemModel.is_sold == False)
                        price_result = await db.execute(price_query)
                        real_item = price_result.scalars().first()
                        
                        if not real_item:
                            reply_text = f"抱歉老板，您想买的【{item_name}】刚才好像被别人抢先拍下，或者库存出现异常了。要不要看看别的？"
                        else:
                            if real_item.inventory > 0:
                                real_item.inventory -= 1
                            if real_item.inventory == 0:
                                real_item.is_sold = True
                            
                            try:
                                await db.flush()
                                send_feishu_alert_task.delay(real_item.name, real_item.price, current_user.email, address)
                                await db.commit()
                                reply_text = f"🎉 搞定啦老板！您的【{real_item.name}】已经为您下单，我们马上安排发往：**{address}**！"
                            except Exception as e:
                                print(f"❌ [订单异常] {e}")
                                await db.rollback()
                                reply_text = "抱歉老板，系统刚打了个冷颤，订单没能写入成功，钱没扣，请稍后再试！"
                                
                elif tool_call_name == "search_web_price":
                    item_name = tool_call_args.get("item_name", "")
                    if item_name:
                        await send_feishu_message(sender_id, f"🕸️ 正在启动量子爬虫，潜入全网为老板搜索 **{item_name}** 的底价，请稍候...")
                        market_data = await search_market_price(item_name)
                        summary_prompt = f"请用一两句话简短总结以下搜到的价格情报，告诉用户外面的价格是多少，并说一句我们平台的价格更香：\n{market_data}"
                        summary_response = await asyncio.to_thread(
                            ai_client.chat.completions.create,
                            model="glm-4.5-flash",
                            messages=[{"role": "user", "content": summary_prompt}],
                            temperature=0.3
                        )
                        summary_text = summary_response.choices[0].message.content
                        reply_text = f"[全网价格情报：{item_name}]\n{summary_text}"
            else:
                reply_text = message_obj.content

            # 💾 保存AI的回复到历史
            if reply_text:
                new_ai_record = models.AIChatRecord(user_id=current_user.id, role="assistant", content=reply_text)
                db.add(new_ai_record)
                await db.commit()
                
                # 调用发信引擎把消息发回去
                await send_feishu_message(sender_id, reply_text)


    except Exception as e:
        print(f"❌ [后台接管] 处理飞书消息时崩溃: {e}")

# ==========================================
# 📡 网关：飞书事件接收器 (保持不变)
# ==========================================
@router.post("/webhook")
async def feishu_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        payload = await request.json()
        print(f"🔥 RAW PAYLOAD: {payload}")
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON"}, status_code=400)

    # 🤝 1. URL 验证 (Challenge)
    if payload.get("type") == "url_verification" or "challenge" in payload:
        return {"challenge": payload.get("challenge")}

    # 🛡️ 2. 安全防线 (验证 Token)
    token = payload.get("token") or payload.get("header", {}).get("token")
    if token != FEISHU_VERIFICATION_TOKEN:
        return JSONResponse(content={"error": "Forbidden"}, status_code=403)

    # ✉️ 3. 处理真实聊天消息
    if payload.get("header", {}).get("event_type") == "im.message.receive_v1":
        event_data = payload.get("event", {})
        background_tasks.add_task(process_feishu_message, event_data)
        return {"msg": "ok"}

    open_id: str