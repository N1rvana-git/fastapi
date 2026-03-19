import re

with open("src/feishu/router.py", "r", encoding="utf-8") as f:
    content = f.read()

# Make sure delete is imported from sqlalchemy
content = content.replace("from sqlalchemy import select, desc", "from sqlalchemy import select, desc, delete")
content = content.replace("from sqlalchemy import select, desc, delete, delete", "from sqlalchemy import select, desc, delete")


old_block = """            # ✅ 场景 B：查到了！是尊贵的业主！
            print(f"✅ 身份确认：飞书用户 {sender_id} 是我们尊贵的业主：{current_user.username}")

            # 1. 💾 记忆写入 1：保存用户刚刚说的话"""


new_block = """            # ✅ 场景 B：查到了！是尊贵的业主！
            print(f"✅ 身份确认：飞书用户 {sender_id} 是我们尊贵的业主：{current_user.username}")

            if user_text.strip() == "/del texts":
                delete_stmt = delete(models.AIChatRecord).where(models.AIChatRecord.user_id == current_user.id)
                await db.execute(delete_stmt)
                await db.commit()
                await send_feishu_message(sender_id, "✅ 您的历史聊天记录已成功清除！我们可以重新开始聊天啦。")
                print(f"🧹 已清空这名用户({current_user.username})的聊天记录")
                return

            # 1. 💾 记忆写入 1：保存用户刚刚说的话"""

content = content.replace(old_block, new_block, 1)

with open("src/feishu/router.py", "w", encoding="utf-8") as f:
    f.write(content)

