with open("src/feishu/router.py", "r", encoding="utf-8") as f:
    content = f.read()

# find Redis call
old_redis = """        # ==========================================
        # 🛑 智能闸机：Redis 分布式高并发限流
        # ==========================================
        if sender_id != "unknown":
            # 1. 制作每个用户专属的“计次卡”名字
            rate_limit_key = f"feishu:rate_limit:{sender_id}"
            
            # 2. Redis 原子操作：在卡上打孔 (+1)
            # incr 的好处是，如果 key 不存在，它会自动创建并设为 1
            current_count = await redis_client.incr(rate_limit_key)"""

new_redis = """        # ==========================================
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
                """
content = content.replace(old_redis, new_redis)
with open("src/feishu/router.py", "w", encoding="utf-8") as f:
    f.write(content)

