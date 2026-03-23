with open("src/feishu/router.py", "r") as f:
    text = f.read()

import re
# Use string literal split on the actual newlines that got put there
pattern = r'"content": "你也是闲小宝飞书分机.*?面对你的老板" \+ current_user.username \+ "。\n\n" \+ SALES_AGENT_SYSTEM_PROMPT.format\(db_data_str=db_data_str\)'
replacement = '                    "content": f"你也是闲小宝飞书分机，保持和网页端一致的人设。面对你的老板{current_user.username}。\\n\\n" + SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)'

# let's just do a simple split and replace
lines = text.split('\n')
for i, line in enumerate(lines):
    if '面对你的老板' in line:
        lines[i] = '                    "content": f"你也是闲小宝飞书分机，保持和网页端一致的人设。面对你的老板{current_user.username}。\\n\\n" + SALES_AGENT_SYSTEM_PROMPT.format(db_data_str=db_data_str)'
        # remove the next blank line and following append line
        if lines[i+1].strip() == '':
            lines.pop(i+1)
        if '" + SALES_AGENT_SYSTEM_PROMPT' in lines[i+1]:
            lines.pop(i+1)
        break

with open("src/feishu/router.py", "w") as f:
    f.write('\n'.join(lines))
