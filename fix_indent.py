with open("src/feishu/router.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if line.strip() == "async def process_feishu_message(event_data: dict):" and i > 100:
        continue
    if "try:" in line and i > 110 and i < 118:
        continue
    if "# ... (前面解析 event_data 的代码保持不变) ..." in line:
        continue
    if "sender_id = event_data.get(\"sender\", {}).get(\"sender_id\", {}).get(\"open_id\", \"unknown\")" in line and i > 110 and i < 120:
        continue
    if "user_text = content_dict.get(\"text\", \"\")" in line and i > 110 and i < 120:
        continue
    if "print(f\"🤖 [后台接管] 收到用户 {sender_id} 的消息: '{user_text}'\")" in line and i > 110 and i < 125:
        continue
    new_lines.append(line)

with open("src/feishu/router.py", "w", encoding="utf-8") as f:
    f.writelines(new_lines)
