import httpx
import json
import asyncio
from fastapi import APIRouter, Request, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from zhipuai import AsyncZhipuAI

router = APIRouter(prefix="/feishu", tags=["Feishu"])

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
ai_client = AsyncZhipuAI(api_key="b40d93bc3d5748dd9fd47efdc32d0f0c.nhsV68wYizfmYx6v")

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
        # 🌟 体验时刻：接入大语言模型！
        # ==========================================
        response = await ai_client.chat.completions.create(
            model="glm-4-flash",
            messages=[
                {"role": "system", "content": "你是一个幽默、机智的私人管家，名字叫“闲小宝飞书分机”。你的回答应该直接且自然。"},
                {"role": "user", "content": user_text}
            ]
        )
        
        reply_text = response.choices[0].message.content
        
        # 调用刚写好的发信引擎，把消息打回用户手机！
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

    return {"msg": "ignored"}