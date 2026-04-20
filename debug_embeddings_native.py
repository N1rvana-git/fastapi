import json, urllib.request, os

token = os.environ.get('ZHIPUAI_API_KEY', '')
if not token:
    print('ZHIPUAI_API_KEY not set; aborting')
    raise SystemExit(1)

req = urllib.request.Request(
    'https://open.bigmodel.cn/api/paas/v4/embeddings',
    headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    },
    data=json.dumps({
        "model": "embedding-3",
        "input": "hello"
    }).encode()
)
try:
    with urllib.request.urlopen(req, timeout=10) as res:
        print(res.status, res.read().decode()[:200])
except Exception as e:
    print("Error:", type(e), e, getattr(e, 'read', lambda: b'')().decode())
