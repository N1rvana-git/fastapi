import sys

with open("src/posts/router.py", "r", encoding="utf-8") as f:
    content = f.read()

# Fix for Message object not having 'get' attribute
old_code = """    user_history_texts = [
        msg.content if hasattr(msg, "content") else msg.get("content", "") 
        for msg in history_list 
        if getattr(msg, "role", msg.get("role", "")) == "user"
    ]"""

new_code = """    user_history_texts = [
        msg.content if hasattr(msg, "content") else msg.get("content", "") if isinstance(msg, dict) else ""
        for msg in history_list 
        if (msg.role if hasattr(msg, "role") else msg.get("role", "") if isinstance(msg, dict) else "") == "user"
    ]"""

if old_code in content:
    content = content.replace(old_code, new_code)
    print("Fixed user_history_texts bug")
else:
    print("Could not find the target code for user_history_texts")

with open("src/posts/router.py", "w", encoding="utf-8") as f:
    f.write(content)
