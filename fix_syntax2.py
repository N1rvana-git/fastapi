with open("src/feishu/router.py", "r") as f:
    text = f.read()

import re
# find the messages list definition and replace it
pattern = r"messages = \[\s*\{\s*\"role\":\s*\"system\",\s*\"content\":\s*.*?\}\s*\]"
replacement = """messages = [
                {
                    "role": "system", 
                    "content": "你也是闲小宝飞书分机，保持和网页端一致的人设。面对你的老板" + current_user.username + "。\\n\\n" + SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)
                }
            ]"""

text = re.sub(pattern, replacement, text, flags=re.DOTALL)
with open("src/feishu/router.py", "w") as f:
    f.write(text)
