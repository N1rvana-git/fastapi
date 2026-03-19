import asyncio
from src.feishu.router import process_feishu_message

event_data = {"message": {"chat_id": "oc_23425c037c2615e21ee6bfd38803f1cf", "chat_type": "p2p", "content": "{\"text\":\"测试\"}", "create_time": "1773902404025", "mentions": [{"id": {"open_id": "ou_689befed2de22d517989592fb528b131", "union_id": "on_1d4ee3abe40909593aa118b0163bf50d", "user_id": None}, "key": "@_user_1", "name": "AI销售", "tenant_key": "1bf5d608bfae1758"}], "message_id": "om_x100b548deaf13c8cc4c9a0558792d86", "message_type": "text", "update_time": "1773902404123", "user_agent": "Mozilla/5.0"}, "sender": {"sender_id": {"open_id": "ou_f475a2e5906c042a4422f915f5c2a61b", "union_id": "on_7b4d9796ecd450346f3de3d8630eda0f", "user_id": None}, "sender_type": "user", "tenant_key": "1bf5d608bfae1758"}}

async def test():
    try:
        await process_feishu_message(event_data)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(test())
