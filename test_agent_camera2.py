import requests

payload = {
    "messages": [
        {"role": "user", "content": "我想了解佳能"},
        {"role": "assistant", "content": "有的，我们有一款佳能相机"},
        {"role": "user", "content": "你介绍一下它"},
        {"role": "assistant", "content": "这是12999的相机"},
        {"role": "user", "content": "我想了解功能"}
    ]
}

res = requests.post("http://localhost:8000/items/ai/agent", json=payload)
print(res.json().get("reply", res.text))
