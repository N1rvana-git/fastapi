import re
with open("src/posts/router.py", "r") as f:
    text = f.read()

# We want to replace the whole body of `async def generate_chat_stream():`
# from   `print("🤖 [Agent 核心]` down to `yield "data: [DONE]\n\n"`

match = re.search(r'(    async def generate_chat_stream\(\):\n)([\s\S]*?)(        yield "data: \[DONE\]\\n\\n"\n)', text)
if match:
    prefix = match.group(1)
    body = match.group(2)
    suffix = match.group(3)
    
    # Indent the body by 4 spaces
    indented_body = "\n".join("    " + line if line.strip() else line for line in body.split("\n"))
    
    # Indent the suffix too (it had 8 spaces, so `    ` + `        yield ...`)
    # wait suffix is `        yield ...` which is 8 spaces. If we indent it, it'll have 12.
    
    new_suffix = '            yield "data: [DONE]\\n\\n"\n'
    
    exception_block = """        except Exception as e:
            import traceback
            traceback.print_exc()
            err_msg = f"\\n\\n🚨 [系统提示] AI思考时发生异常或网络中断，原因是: {str(e)}"
            yield f"data: {json.dumps({'content': err_msg})}\\n\\n"
            yield "data: [DONE]\\n\\n"
"""
    
    new_block = prefix + "        try:\n" + indented_body + new_suffix + exception_block
    
    new_text = text[:match.start()] + new_block + text[match.end():]
    
    with open("src/posts/router.py", "w") as f:
        f.write(new_text)
    print("Fixed router.py successfully!")
else:
    print("Could not find the function body in router.py.")
