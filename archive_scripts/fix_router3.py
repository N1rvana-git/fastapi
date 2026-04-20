import re

with open("src/posts/router.py", "r") as f:
    text = f.read()

# We'll dynamically find where `generate_chat_stream()` starts and ends.
match = re.search(r'(    async def generate_chat_stream\(\):\n)([\s\S]*?)(        yield "data: \[DONE\]\\n\\n"\n)', text)
if not match:
    print("Match failed!")
    exit(1)

prefix = match.group(1)
body = match.group(2)
suffix = match.group(3)

# add 4 spaces to each non-empty line of the body:
new_body_lines = []
for line in body.split("\n"):
    if line.strip():
        new_body_lines.append("    " + line)
    else:
        new_body_lines.append(line)
new_body = "\n".join(new_body_lines)

# new suffix: it originally had 8 spaces. We want to indent the original suffix by 4 spaces.
new_suffix_lines = [("    " + line if line.strip() else line) for line in suffix.split("\n")]
new_suffix = "\n".join(new_suffix_lines)

# Now we add the except block at the same level as the `try:` (which is 8 spaces in)
except_block = """        except Exception as e:
            import traceback; traceback.print_exc()
            import json
            err_msg = f"\\n\\n🚨 [系统提示] AI思考时发生异常或网络中断，原因是: {str(e)}"
            yield f"data: {json.dumps({'content': err_msg})}\\n\\n"
            yield "data: [DONE]\\n\\n"
"""

new_function = prefix + "        try:\n" + new_body + new_suffix + except_block

new_text = text[:match.start()] + new_function + text[match.end():]

with open("src/posts/router.py", "w") as f:
    f.write(new_text)
print("Router repaired!")
