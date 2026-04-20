import re

with open("src/posts/router.py", "r", encoding="utf-8") as f:
    content = f.read()

with open("temp_new.py", "r", encoding="utf-8") as f:
    new_code = "# === 🌟 核心大脑：带物理外挂的 Agent ===\n" + f.read()

pattern = re.compile(
    r'# === 🌟 核心大脑：带物理外挂的 Agent ===\s*@router\.post\("/ai/agent"\).*?return StreamingResponse\(generate_chat_stream\(\), media_type="text/event-stream"\)',
    re.DOTALL
)

if pattern.search(content):
    new_content = pattern.sub(new_code, content, count=1)
    with open("src/posts/router.py", "w", encoding="utf-8") as f:
        f.write(new_content)
    print("Replace success")
else:
    print("Pattern not found")

