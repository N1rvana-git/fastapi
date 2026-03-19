with open("src/feishu/router.py", "r", encoding="utf-8") as f:
    content = f.read()

old_redis2 = """            # 3. 如果是第一次打孔，给这张卡设定一个 60 秒后自动销毁的定时炸弹！
            if current_count == 1:
                await redis_client.expire(rate_limit_key, 60)"""

new_redis2 = """            # 3. 如果是第一次打孔，给这张卡设定一个 60 秒后自动销毁的定时炸弹！
            if current_count == 1:
                try:
                    await redis_client.expire(rate_limit_key, 60)
                except Exception:
                    pass"""

content = content.replace(old_redis2, new_redis2)
with open("src/feishu/router.py", "w", encoding="utf-8") as f:
    f.write(content)
