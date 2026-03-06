import requests

try:
    r = requests.post("http://localhost:8000/items/ai/agent", json={"message": "你好", "history": []})
    print(r.status_code, r.text)
except Exception as e:
    print(e)
