with open("temp_new.py", "w", encoding="utf-8") as f:
    f.write(r"""@router.post("/ai/agent")
async def agent_with_tools(
    request: AgentRequest, 
    db: AsyncSession = Depends(get_db_session),
    current_user = Depends(get_current_user)
):
    history_list = request.history or request.messages or []
    last_user_msg = history_list[-1].content if history_list else ""
    
    # 1. 💾 保存用户的提问到数据库
    new_user_record = models.AIChatRecord(user_id=current_user.id, role="user", content=last_user_msg)
    db.add(new_user_record)
    await db.commit()

    # ===================================================
    # 🔍 保留你原有的穷人版 RAG (第一期我们先不动它)
    # ===================================================
    user_history_texts = [
        msg.content if hasattr(msg, "content") else msg.get("content", "") if isinstance(msg, dict) else ""
        for msg in history_list 
        if (msg.role if hasattr(msg, "role") else msg.get("role", "") if isinstance(msg, dict) else "") == "user"
    ]
    
    recent_user_texts = user_history_texts[-3:]
    search_query = " ".join(recent_user_texts)

    print(f"🔫 [向量检索] 融合语境搜索词: '{search_query}'")
    try:
        embed_response = ai_client.embeddings.create(model="embedding-2", input=search_query)
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
            print("⚠️ [向量检索] 未命中任何带向量的商品，触发传统保底扫描...")
            backup_query = select(models.ItemModel).where(models.ItemModel.inventory > 0).limit(5)
            backup_result = await db.execute(backup_query)
            items = backup_result.scalars().all()
        db_data_str = "当前没有任何商品。" if not items else "、".join([f"ID:{item.id}-{item.name}(￥{item.price}, 剩余{item.inventory}件)" for item in items])
        print(f"🎯 [向量检索] 匹配成功！库存：{db_data_str}")
    except Exception as e:
        print(f"⚠️ [向量检索] 失败: {e}")
        db_data_str = "库存检索失败"
    
    # ===================================================
    # 🌟 架构师魔法：将对话转为 LangChain 标准 Message
    # ===================================================
    messages = [
        SystemMessage(content=SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str))
    ]

    # 截断历史，保留最近 6 条
    recent_history = history_list[-6:] if history_list else []
    for msg in recent_history:
        role = getattr(msg, "role", "user") if hasattr(msg, "role") else msg.get("role", "user")
        content = getattr(msg, "content", "") if hasattr(msg, "content") else msg.get("content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))

    # 如果是空对话，给个默认打招呼
    if not recent_history:
        messages.append(HumanMessage(content="你好"))

    # ===================================================
    # 🌟 核心引擎：LangGraph 流式打字机 (完全取代旧版逻辑)
    # ===================================================
    async def generate_chat_stream():
        print("🤖 [LangGraph] 引擎点火！启动状态机流式推理...")
        full_reply_text = ""

        # stream_mode="messages" 极其强大！它会把 Graph 运行中产生的【每一个字】和【工具执行结果】都推出来！
        async for msg, metadata in graph.astream({"messages": messages}, stream_mode="messages"):
            
            # 🎯 拦截 1：大模型正常的文字回复 (打字机效果)
            if msg.type == "ai" and msg.content and isinstance(msg.content, str):
                full_reply_text += msg.content
                yield f"data: {json.dumps({'content': msg.content})}\n\n"

            # 🎯 拦截 2：大模型决定调用工具的瞬间 (给前端发提示语)
            if msg.type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_name = msg.tool_calls[0]['name']
                if tool_name == "search_web_price":
                    yield f"data: {json.dumps({'content': '\n\n🕸️ [LangGraph] 正在启动量子爬虫进行全网比价，请稍候...'})}\n\n"
                elif tool_name == "create_order":
                    yield f"data: {json.dumps({'content': '\n\n📦 [LangGraph] 正在为您查验库存并生成订单...'})}\n\n"

            # 🎯 拦截 3：工具执行完毕的返回结果 (发送前端专属 UI 卡片！)
            if msg.type == "tool":
                print(f"🛠️ [工具执行完毕] {msg.name} 返回了结果！")
                
                if msg.name == "search_web_price":
                    # 🌟 向前端 Vue 发送特殊的【结构化卡片标记】！
                    card_data = {
                        "content": "\n\n", 
                        "specialType": "price_card",
                        "itemName": "全网比价情报",
                        "marketPriceSummary": msg.content
                    }
                    yield f"data: {json.dumps(card_data)}\n\n"
                    full_reply_text += f"\n[展示了价格卡片]\n{msg.content}"
                    
                elif msg.name == "create_order":
                    result_msg = f"\n\n🛡️ [交易结果]: {msg.content}"
                    full_reply_text += result_msg
                    yield f"data: {json.dumps({'content': result_msg})}\n\n"

        # 💾 对话结束，把最终拼好的完整回复存入数据库
        new_ai_record = models.AIChatRecord(user_id=current_user.id, role="assistant", content=full_reply_text)
        db.add(new_ai_record)
        await db.commit()
        
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate_chat_stream(), media_type="text/event-stream")""")
