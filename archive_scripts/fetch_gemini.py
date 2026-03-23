import urllib.request
import re
import json

url = "https://gemini.google.com/share/99598ee7dd80"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    html = urllib.request.urlopen(req).read().decode('utf-8')
    # Find all text that looks like Chinese characters or common programming terms
    # Alternatively just extract AF_initDataCallback
    matches = re.findall(r'AF_initDataCallback\(({.*?})\);', html)
    for m in matches:
        if "fastapi" in m.lower() or "python" in m.lower() or "api" in m.lower() or "教程" in m.lower():
            print(m[:1000])
            
    # As a fallback, just regex extract common readable text from the raw html
    raw_text = re.sub('<[^<]+?>', ' ', html)
    print(raw_text[:1000])
except Exception as e:
    print("Error:", e)
