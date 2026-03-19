with open("src/feishu/router.py", "r") as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if "你也是闲小宝飞书分机" in line:
        lines[i] = '                    "content": "你也是闲小宝飞书分机，保持和网页端一致的人设。面对你的老板" + current_user.username + "。\\n\\n" + SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)\n'
        break

with open("src/feishu/router.py", "w") as f:
    f.writelines(lines)
