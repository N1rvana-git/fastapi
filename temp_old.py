    db: AsyncSession = Depends(get_db_session),
    current_user = Depends(get_current_user)
):
    history_list = request.history or request.messages or []
    last_user_msg = history_list[-1].content if history_list else ""
    
    # 1. 💾 记忆写入 1：保存用户刚刚说的话
    # 1. 💾 存用户消息进数据库
    new_user_record = models.AIChatRecord(user_id=current_user.id, role="user", content=last_user_msg)
    db.add(new_user_record)
    await db.commit()

    # ===================================================
    # 🌟 架构师外挂升级：上下文感知检索 (Contextual RAG)
    # ===================================================
    # 提取上下文中所有用户的发言，以防止语义断层！
    user_history_texts = [
        msg.content if hasattr(msg, "content") else msg.get("content", "") if isinstance(msg, dict) else ""
        for msg in history_list 
        if (msg.role if hasattr(msg, "role") else msg.get("role", "") if isinstance(msg, dict) else "") == "user"
    ]
    
    # 🌟 核心魔法：使用最近的最多 3 条用户发言（滑动窗口），防止深层聊天时语义完全断层丢失上下文！
    recent_user_texts = user_history_texts[-3:]
    search_query = " ".join(recent_user_texts)

    print(f"🔫 [向量检索] 融合语境搜索词: '{search_query}'")
    try:
        embed_response = ai_client.embeddings.create(model="embedding-2", input=search_query)
        query_vector = embed_response.data[0].embedding

        query = (
            select(models.ItemModel)
            .where(models.ItemModel.is_offer == True)
            .where(models.ItemModel.inventory > 0) # 🌟 唯一真理：只要有库存，就允许卖！
            .where(models.ItemModel.embedding.is_not(None))
            .order_by(models.ItemModel.embedding.cosine_distance(query_vector))
            .limit(3)
        )
        result = await db.execute(query)
        items = list(result.scalars().all())
        
        # 🌟 强行补充传统文本包含匹配：因为如果有商品没有生成向量，向量检索就永远查不到！
        text_query = select(models.ItemModel).where(models.ItemModel.is_offer == True).where(models.ItemModel.inventory > 0)
        text_result = await db.execute(text_query)
        all_text_items = text_result.scalars().all()
        
        for item in all_text_items:
            # 如果商品名称里的连续2个字出现在用户询问中，强制纳入结果（非常粗暴有效的兜底）
            # 或者用户的长词出现在商品名中（如"相机" in "尼康相机"）
            match = False
            if len(search_query) >= 2:
                for i in range(len(search_query)-1):
                    bi_gram = search_query[i:i+2]
                    if len(bi_gram.strip()) == 2 and bi_gram in item.name:
                        match = True
                        break
            if match and item not in items:
                items.append(item)

        # 如果因为 Celery 没跑导致商品没有向量，或者算力偏差找不到，强行用传统 SQL 抓取最新商品！
        if not items:
            print("⚠️ [向量检索] 未命中任何带向量的商品，触发传统保底扫描...")
            # ❌ 同样在这里删掉 is_sold == False ！！
            backup_query = select(models.ItemModel).where(models.ItemModel.inventory > 0).limit(5)
            backup_result = await db.execute(backup_query)
            items = backup_result.scalars().all()
        db_data_str = "当前没有任何商品。" if not items else "、".join([f"ID:{item.id}-{item.name}(￥{item.price}, 剩余{item.inventory}件)" for item in items])
        print(f"🎯 [向量检索] 匹配成功！库存：{db_data_str}")
    except Exception as e:
        print(f"⚠️ [向量检索] 失败: {e}")
        db_data_str = "库存检索失败"

    # ===================================================
    # 🛡️ 架构师最终版状态机：加入售后护栏
    # ===================================================
    messages = [
        {
            "role": "system", 
            # 🌟 动态注入库存数据到 Prompt 模板中！
            "content": SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)
        }
    ]

    MAX_CONTEXT_MESSAGES = 6 
    if history_list:
        # 像切除肿瘤一样，只切取列表最末尾的 MAX_CONTEXT_MESSAGES 条记录
        recent_history = history_list[-MAX_CONTEXT_MESSAGES:]
        print(f"✂️ [上下文截断] 原始对话长度: {len(history_list)}，截断后保留: {len(recent_history)}")
        for msg in recent_history:
            role = getattr(msg, "role", "user") if hasattr(msg, "role") else msg.get("role", "user")
            content = getattr(msg, "content", "") if hasattr(msg, "content") else msg.get("content", "")
            messages.append({"role": role, "content": content})
    else:
        messages.append({"role": "user", "content": "你好"})

    # 4. 🛠️ 极其严格的 Tools 定义 (要求必须传 item_id)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "search_web_price",
                "description": "🚨【极度危险】当且仅当用户明确要求查看【外部市场价】、【全网比价】、【别人卖多少钱】时才允许调用！如果用户只是询问本平台有什么商品，绝对、绝对禁止调用此工具！",
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

    # === 🌟 核心魔法：异步流式生成器 (将原本的逻辑包裹进来) ===
    async def generate_chat_stream():
        print("🤖 [Agent 核心] 开启水龙头！向带有 Tools 的云端大脑发送流式请求...")
        response = ai_client.chat.completions.create(
            model="glm-4.5-flash", 
            messages=messages,
            tools=tools,
            stream=True  # 👈 核心参数：开启流！
        )
        
        tool_call_name = ""
        tool_call_args = ""
        full_reply_text = ""

        # 🌟 滴水穿石：读取打字机输出
        for chunk in response:
            delta = chunk.choices[0].delta
            
            # 悄悄拦截工具调用的 JSON 字符串片段
            if delta.tool_calls:
                tc = delta.tool_calls[0]
                if tc.function.name: tool_call_name += tc.function.name
                if tc.function.arguments: tool_call_args += tc.function.arguments
                yield ":keep-alive\n\n"  # 给前端发送一个心跳包，保持连接不断开
            # 直接将正常的聊天文字喷射给前端
            elif delta.content:
                full_reply_text += delta.content
                yield f"data: {json.dumps({'content': delta.content})}\n\n"
        
        # ==========================================
        # 🌟 流接收完毕！在这里执行你的【绝对防御业务逻辑】
        # ==========================================
        # ==========================================
        # 🌟 流接收完毕！在这里执行你的【绝对防御业务逻辑】
        # ==========================================
        if tool_call_name == "create_order":
            print(f"⚡ [Function Calling] 拦截到完整参数: {tool_call_args}")
            args = json.loads(tool_call_args)
            
            try:
                item_id = int(args.get("item_id", 0))
            except ValueError:
                item_id = 0
            item_name = args.get("item_name", "未知商品")
            address = args.get("address", "") # 默认设为空
            
            # === 🌟 架构师的终极防骗拦截：没地址？滚回去问！ ===
            if not address or len(address) < 5 or address == "未知地址":
                print("❌ [安全拦截] AI 试图在没有地址的情况下发货，已打回！")
                refuse_msg = f"\n\n老板，您还没告诉我**详细的收货地址**呢！请把省市区街道等详细地址发我，我立刻给您下单【{item_name}】！"
                full_reply_text += refuse_msg
                yield f"data: {json.dumps({'content': refuse_msg})}\n\n"
            else:
                # === 地址正常，开始核实数据库 ===
                print(f"🛡️ [安全校验] 正在数据库核实 ID={item_id} 的真实存在与价格...")
                price_query = select(models.ItemModel).where(models.ItemModel.id == item_id).where(models.ItemModel.is_offer == True).where(models.ItemModel.is_sold == False)
                price_result = await db.execute(price_query)
                real_item = price_result.scalars().first()
                
                if not real_item:
                    fail_msg = f"\n\n抱歉老板，您想买的【{item_name}】刚才好像被别人抢先拍下，或者库存出现异常了。要不要看看别的？"
                    full_reply_text += fail_msg
                    yield f"data: {json.dumps({'content': fail_msg})}\n\n"
                else:
                    # 1. 安全扣减库存
                    if real_item.inventory > 0:
                        real_item.inventory -= 1

                        # 确保库存扣减后持久化
                        await db.flush()

                        # 只有库存真正归零时，才将状态锁死为售罄
                        if real_item.inventory == 0:
                            real_item.is_sold = True
                            await db.flush()

                    # 提交事务，确保所有改动生效
                    await db.commit()
                    
                    success_msg = f"\n\n🎉 搞定啦老板！您的【{real_item.name}】已经为您下单，我们马上安排发往：**{address}**！"
                    full_reply_text += success_msg
                    yield f"data: {json.dumps({'content': success_msg})}\n\n"
                await db.commit()
        elif tool_call_name == "search_web_price":
            print(f"⚡ [Function Calling] AI 想要全网比价！参数: {tool_call_args}")
            args = json.loads(tool_call_args)
            item_name = args.get("item_name", "")
            
            if item_name:
