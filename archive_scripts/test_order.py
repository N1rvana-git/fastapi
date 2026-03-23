import requests

payload = {
    "messages": [
        {"role": "user", "content": "我要买索尼微单，地址是1省2市3区4街道5楼6号"}
    ]
}

res = requests.post("http://localhost:8000/items/ai/agent", json=payload)
print(res.json().get("reply", res.text))
