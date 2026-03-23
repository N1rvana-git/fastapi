import requests

payload = {
    "messages": [
        {"role": "user", "content": "到底有没有相机啊"}
    ]
}

res = requests.post("http://localhost:8000/items/ai/agent", json=payload)
print(res.json().get("reply", res.text))
