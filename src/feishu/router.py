import httpx
import json
import asyncio
from pydantic import BaseModel
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from zhipuai import ZhipuAI

# 引入数据库工厂和 user service
from src.database import AsyncSessionLocal
from src.posts import service as posts_service 
from src.auth.dependencies import get_current_user
from src.posts.dependencies import get_db_session
from src.posts import models
from src.posts import service as posts_services
router = APIRouter(prefix="/feishu", tags=["Feishu"])

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
            
            # 为了测试，这里接入之前写好的智谱大模型逻辑：
            # 先给大模型传入用户的名字，让大模型能直接知道用户是谁
            system_prompt = f"你是一个幽默、机智的私人管家，名字叫“闲小宝飞书分机”。你的回答应该直接且自然。现在和你聊天的主人名字是：{current_user.username}"
            
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model="glm-4-flash",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text}
                ]
            )
            
            reply_text = response.choices[0].message.content
            
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