import re

def fix_file(filename):
    with open(filename, "r") as f:
        content = f.read()

    # Find the tools definition for search_web_price and replace it
    # We will replace the parameters block for and only for search_web_price
    
    old_tool_params = """                        "parameters": {
                            "type": "object",
                            "properties": {
                                "item_id": {"type": "integer", "description": "必须提取的商品唯一ID（从提供的后台库存数据中获取）"},
                                "item_name": {"type": "string", "description": "要购买的商品名称"},
                                "address": {"type": "string", "description": "用户的详细收货地址"}
                            },
                            "required": ["item_id", "item_name", "address"]
                        }"""
    
    new_tool_params = """                        "parameters": {
                            "type": "object",
                            "properties": {
                                "item_name": {"type": "string", "description": "要查询或比价的商品名称关键字（如：哈苏X2D、Sony微单等）"}
                            },
                            "required": ["item_name"]
                        }"""
    
    # Just to be safe, find the exact block under search_web_price
    content = content.replace(old_tool_params, new_tool_params, 1) # Only replace the first occurrence (which is search_web_price)
    
    with open(filename, "w") as f:
        f.write(content)

fix_file("src/feishu/router.py")
