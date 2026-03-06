with open("src/posts/router.py", "r") as f:
    text = f.read()

text = text.replace("""    if len(messages) == 1:
        messages.append({"role": "user", "content": "你好，我是用户"})
    print("🚀 [Agent] 发送至智谱的 messages =", messages)

    if len(messages) == 1:
        messages.append({"role": "user", "content": "你好，我是用户"})
    print("🚀 [Agent] 发送至智谱的 messages =", messages)""", """    if len(messages) == 1:
        messages.append({"role": "user", "content": "你好，我是用户"})
    print("🚀 [Agent] 发送至智谱的 messages =", messages)""")

with open("src/posts/router.py", "w") as f:
    f.write(text)
