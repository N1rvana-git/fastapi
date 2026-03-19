import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# 引入你的 FastAPI 主程序
from src.main import app
# 引入你写在 feishu 路由里的真实 TOKEN
from src.feishu.router import FEISHU_VERIFICATION_TOKEN

# 🌟 实例化我们的“模拟邮递员”
client = TestClient(app)

# ==========================================
# 🧪 测试 1：测试飞书的“初次见面” (Challenge 验证)
# ==========================================
def test_feishu_webhook_challenge():
    """测试飞书配置应用时的 URL 验证功能"""
    
    # 1. 伪造飞书发来的小纸条
    fake_payload = {
        "challenge": "fake_challenge_12345",
        "type": "url_verification"
    }
    
    # 2. 邮递员出动！往你的接口发 POST 请求
    response = client.post("/feishu/webhook", json=fake_payload)
    
    # 3. 极其严谨的断言 (Assert) 环节：检查结果是不是我们想要的
    assert response.status_code == 200
    assert response.json() == {"challenge": "fake_challenge_12345"}


# ==========================================
# 🧪 测试 2：测试真实聊天 (引入“替身演员” Mock)
# ==========================================
# 🌟 @patch 就是请替身演员！我们要把后台真正去处理消息、调大模型的那个函数给“拦住”！
@patch("src.feishu.router.process_feishu_message")
def test_feishu_receive_message(mock_process_message):
    """测试接收到真实聊天消息时，系统是否正确交接给后台任务"""
    
    # 1. 伪造一条真实的聊天数据包
    fake_payload = {
        "header": {
            "event_type": "im.message.receive_v1", 
            "token": FEISHU_VERIFICATION_TOKEN # 必须带上真 Token，否则会被你的安全防线拦住！
        },
        "event": {
            "message": {
                "message_type": "text", 
                "content": '{"text":"你好，闲小宝"}'
            }
        }
    }
    
    # 2. 邮递员出动！
    response = client.post("/feishu/webhook", json=fake_payload)
    
    # 3. 检查门面服务员 (Router) 是不是马上返回了 ok，没有超时
    assert response.status_code == 200
    assert response.json() == {"msg": "ok"}
    
    # 4. 🌟 最牛的断言：拷问替身演员！
    # 检查那个耗时的后台大脑函数，是不是真的被触发了？
    # (如果这里没报错，说明 BackgroundTasks 完美执行了交接！)
    mock_process_message.assert_called_once()