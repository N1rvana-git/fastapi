import re

with open("src/posts/router.py", "r", encoding="utf-8") as f:
    text = f.read()

# Define the new method
new_generate = r"""    async def generate_chat_stream():
        print("🤖 [LangGraph] 引擎点火！启动状态机流式推理...")
        full_reply_text = ""

        try:
            # stream_mode="messages" 极其强大！它会把 Graph 运行中产生的【每一个字】和【工具执行结果】都推出来！
            async for msg, metadata in graph.astream({"messages": messages}, stream_mode="messages"):
                
                # 🎯 拦截 1：大模型正常的文字回复 (打字机效果)
                if msg.type == "ai" and msg.content and isinstance(msg.content, str):
                    full_reply_text += msg.content
                    import json
                    yield f"data: {json.dumps({'content': msg.content})}\n\n"
    
                # 🎯 拦截 2：大模型决定调用工具的瞬间 (给前端发提示语)
                if msg.type == "ai" and hasattr(msg, "tool_calls") and msg.tool_calls:
                    tool_name = msg.tool_calls[0]["name"]
                    if tool_name == "search_web_prices":
                        import json
                        yield f"data: {json.dumps({'content': chr(10) + chr(10) + '🕸️ [LangGraph] 正在启动量子爬虫进行全网比价，请稍候...'})}\n\n"
                    elif tool_name == "create_order":
                        import json
                        yield f"data: {json.dumps({'content': chr(10) + chr(10) + '📦 [LangGraph] 正在为您查验库存并生成订单...'})}\n\n"
    
                # 🎯 拦截 3：工具执行完毕的返回结果 (发送前端专属 UI 卡片！)
                if msg.type == "tool":
                    print(f"🛠️ [工具执行完毕] {msg.name} 返回了结果！")
                    
                    if msg.name == "search_web_prices":
                        import json
                        card_data = {
                            "content": "\n\n", 
                            "specialType": "price_card",
                            "itemName": "全网比价情报",
                            "marketPriceSummary": msg.content
                        }
                        yield f"data: {json.dumps(card_data)}\n\n"
                        full_reply_text += f"\n[展示了价格卡片]\n{msg.content}"
                        
                    elif msg.name == "create_order":
                        import json
                        result_msg = f"\n\n🛡️ [交易结果]: {msg.content}"
                        full_reply_text += result_msg
                        yield f"data: {json.dumps({'content': result_msg})}\n\n"

            # 💾 对话结束，把最终拼好的完整回复存入数据库
            new_ai_record = models.AIChatRecord(user_id=current_user.id, role="assistant", content=full_reply_text)
            db.add(new_ai_record)
            await db.commit()
            
            # 宣告本次流式连接彻底结束
            yield "data: [DONE]\n\n"
        except Exception as e:
            print(f"Streaming Error: {e}")
            import traceback, json
            traceback.print_exc()
            yield f"data: {json.dumps({'content': chr(10) + chr(10) + f'❌ 引擎运行报错: {str(e)}'})}\n\n"
            yield "data: [DONE]\n\n"
"""

pattern = r"    async def generate_chat_stream\(\):.*?yield \x22data: \[DONE\]\\n\\n\x22"
replaced = re.sub(pattern, new_generate, text, flags=re.DOTALL)

with open("src/posts/router.py", "w", encoding="utf-8") as f:
    f.write(replaced)

print("Router updated 2!")
