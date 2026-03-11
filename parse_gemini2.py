import urllib.request
import re

url = "https://gemini.google.com/share/99598ee7dd80"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
try:
    resp = urllib.request.urlopen(req).read().decode('utf-8')
    matches = re.findall(r'\[\\"([^\]]+?)\\n\\n', resp)
    for m in matches:
        print(m[:200])
except Exception as e:
    pass
