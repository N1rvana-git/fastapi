import re
with open("src/posts/router.py", "r") as f:
    text = f.read()

text = text.replace('messages = [\n        {"role": "system", "content": "你是闲小宝，一个二手交易平台的 AI 管家。如果有需要，请善用你的工具来回答用户问题。"}\n    ]', 'system_msg = {"role": "system", "content": "你是闲小宝，一个二手交易平台的 AI 管家。如果有需要，请善用你的工具来回答用户问题。"}\n    messages = [system_msg]')

with open("src/posts/router.py", "w") as f:
    f.write(text)
