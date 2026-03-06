import requests

try:
    r = requests.post("http://localhost:8000/items/ai/agent", json={"messages": [{"role": "user", "content": "你好"}]})
    print(r.status_code, r.text)
except Exception as e:
    print(e)
