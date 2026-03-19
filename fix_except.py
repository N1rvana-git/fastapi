with open("src/feishu/router.py", "r", encoding="utf-8") as f:
    content = f.read()

old_except = """
    except Exception as e:
        print(f"❌ [后台处理失败] {e}")"""

new_except = """
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"❌ [后台处理失败] {e}")"""

if "except Exception as e:" not in content:
    print("Could not find exception block")
    # let's just find the end of process_feishu_message
else:
    content = content.replace(old_except, new_except)

with open("src/feishu/router.py", "w", encoding="utf-8") as f:
    f.write(content)

