import re

with open("src/feishu/router.py", "r") as f:
    text = f.read()

imports = """
from sqlalchemy import select, desc
from src.posts.prompts import SALES_AGENT_SYSTEM_PROMPT
from src.posts.scraper import search_market_price
from src.worker import send_feishu_alert_task
"""

text = text.replace("from zhipuai import ZhipuAI\n", f"from zhipuai import ZhipuAI\n{imports}")

# match current_user check till Exception
pattern = r"# ✅ 场景 B：查到了！是尊贵的业主！(.*?)(?=\n\s*except Exception as e:)"

replacement = """# ✅ 场景 B：查到了！是尊贵的业主！
            print(f"✅ 身份确认：飞书用户 {sender_id} 是我们尊贵的业主：{current_user.username}")

            # 1. 💾 记忆写入 1：保存用户刚刚说的话
            new_user_record = models.AIChatRecord(user_id=current_user.id, role="user", content=user_text)
            db.add(new_user_record)
            await db.commit()

            # 获取历史记录
            history_query = (
                select(models.AIChatRecord)
                .where(models.AIChatRecord.user_id == current_user.id)
                .order_by(desc(models.AIChatRecord.created_at))
                .limit(6)
            )
            history_result = await db.execute(history_query)
            history_records = list(history_result.scalars().all())
            history_records.reverse()

            user_history_texts = [r.content for r in history_records if r.role == 'user']
            recent_user_texts = user_history_texts[-3:] if user_history_texts else [user_text]
            search_query = " ".join(recent_user_texts)

            print(f"🔫 [向量检索] 融合语境搜索词: '{search_query}'")
            try:
                embed_response = await asyncio.to_thread(
                    ai_client.embeddings.create,
                    model="embedding-2", 
                    input=search_query
                )
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
                    backup_query = select(models.ItemModel).where(models.ItemModel.inventory > 0).limit(5)
                    backup_result = await db.execute(backup_query)
                    items = backup_result.scalars().all()
                db_data_str = "当前没有任何商品。" if not items else "、".join([f"ID:{item.id}-{item.name}(￥{item.price}, 剩余{item.inventory}件)" for item in items])
            except Exception as e:
                print(f"⚠️ [向量检索] 失败: {e}")
                db_data_str = "库存检索失败"

            messages = [
                {
                    "role": "system", 
                    "content": "你也是闲小宝飞书分机，保持和网页端一致的人设。面对你的老板" + current_user.username + "。\n\n" + SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)
                }
            ]

            for msg in history_records:
                messages.append({"role": msg.role, "content": msg.content})

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
                },
                {
                    "type": "function",
                    "function": {
                        "name": "create_order",
                        "description": "用户说['我要了', '怎么买', '老地址']，在取得详细地址后调用以扣库存和发飞书提醒",
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

            print("🤖 [Agent] 正在思考...")
            response = await asyncio.to_thread(
                ai_client.chat.completions.create,
                model="glm-4.5-flash",
                messages=messages,
                tools=tools,
            )
            
            message_obj = response.choices[0].message
            reply_text = ""
            
            if hasattr(message_obj, 'tool_calls') and message_obj.tool_calls:
                tool_call = message_obj.tool_calls[0]
                tool_call_name = tool_call.function.name
                tool_call_args = json.loads(tool_call.function.arguments)
                
                print(f"⚡ [Function Calling] AI 选择工具: {tool_call_name}, 参数: {tool_call_args}")
                
                if tool_call_name == "create_order":
                    item_id = int(tool_call_args.get("item_id", 0))
                    item_name = tool_call_args.get("item_name", "未知商品")
                    address = tool_call_args.get("address", "")
                    
                    if not address or len(address) < 5 or address == "未知地址":
                        reply_text = f"老板，您还没告诉我**详细的收货地址**呢！请把省市区街道等详细地址发我，我立刻给您下单【{item_name}】！"
                    else:
                        price_query = select(models.ItemModel).where(models.ItemModel.id == item_id).where(models.ItemModel.is_offer == True).where(models.ItemModel.is_sold == False)
                        price_result = await db.execute(price_query)
                        real_item = price_result.scalars().first()
                        
                        if not real_item:
                            reply_text = f"抱歉老板，您想买的【{item_name}】刚才好像被别人抢先拍下，或者库存出现异常了。要不要看看别的？"
                        else:
                            if real_item.inventory > 0:
                                real_item.inventory -= 1
                            if real_item.inventory == 0:
                                real_item.is_sold = True
                            
                            try:
                                await db.flush()
                                send_feishu_alert_task.delay(real_item.name, real_item.price, current_user.email, address)
                                await db.commit()
                                reply_text = f"🎉 搞定啦老板！您的【{real_item.name}】已经为您下单，我们马上安排发往：**{address}**！"
                            except Exception as e:
                                print(f"❌ [订单异常] {e}")
                                await db.rollback()
                                reply_text = "抱歉老板，系统刚打了个冷颤，订单没能写入成功，钱没扣，请稍后再试！"
                                
                elif tool_call_name == "search_web_price":
                    item_name = tool_call_args.get("item_name", "")
                    if item_name:
                        await send_feishu_message(sender_id, f"🕸️ 正在启动量子爬虫，潜入全网为老板搜索 **{item_name}** 的底价，请稍候...")
                        market_data = await search_market_price(item_name)
                        summary_prompt = f"请用一两句话简短总结以下搜到的价格情报，告诉用户外面的价格是多少，并说一句我们平台的价格更香：\\n{market_data}"
                        summary_response = await asyncio.to_thread(
                            ai_client.chat.completions.create,
                            model="glm-4.5-flash",
                            messages=[{"role": "user", "content": summary_prompt}],
                            temperature=0.3
                        )
                        summary_text = summary_response.choices[0].message.content
                        reply_text = f"[全网价格情报：{item_name}]\\n{summary_text}"
            else:
                reply_text = message_obj.content

            # 💾 保存AI的回复到历史
            if reply_text:
                new_ai_record = models.AIChatRecord(user_id=current_user.id, role="assistant", content=reply_text)
                db.add(new_ai_record)
                await db.commit()
                
                # 调用发信引擎把消息发回去
                await send_feishu_message(sender_id, reply_text)
"""

result = re.sub(pattern, replacement, text, flags=re.DOTALL)

with open("src/feishu/router.py", "w") as f:
    f.write(result)
