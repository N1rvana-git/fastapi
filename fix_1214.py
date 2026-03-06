import re
with open("src/posts/router.py", "r") as f:
    text = f.read()

replacement = """    system_msg = {"role": "system", "content": "你是闲小宝，一个二手交易平台的 AI 管家。如果有需要，请善用你的工具来回答用户问题。"}
    messages = [system_msg]
    for msg in (request.history or request.messages or []):
        messages.append({"role": msg.role, "content": msg.content})

    if len(messages) == 1:
        messages.append({"role": "user", "content": "你好，我是用户"})
    print("🚀 [Agent] 发送至智谱的 messages =", messages)"""

text = text.replace("""    system_msg = {"role": "system", "content": "你是闲小宝，一个二手交易平台的 AI 管家。如果有需要，请善用你的工具来回答用户问题。"}
    messages = [system_msg]
    for msg in (request.history or request.messages or []):
        messages.append({"role": msg.role, "content": msg.content})""", replacement)

with open("src/posts/router.py", "w") as f:
    f.write(text)
