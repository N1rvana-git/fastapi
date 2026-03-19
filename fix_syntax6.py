with open("src/feishu/router.py", "r") as f:
    text = f.read()

import re
pattern = r'reply_text = f"\[全网价格情报：\{item_name\}\]\\n.*?\{summary_text\}"'
replacement = '                        reply_text = f"[全网价格情报：{item_name}]\\n{summary_text}"'

# Using a more direct lines manipulation approach since regex with newlines is tricky here
lines = text.split('\n')
for i, line in enumerate(lines):
    if "[全网价格情报：" in line:
        lines[i] = '                        reply_text = f"[全网价格情报：{item_name}]\\n{summary_text}"'
        if '{summary_text}"' in lines[i+1]:
            lines.pop(i+1)
        break

with open("src/feishu/router.py", "w") as f:
    f.write('\n'.join(lines))
