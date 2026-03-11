import urllib.request
import re
import html
import urllib.parse
from html.parser import HTMLParser

url = "https://gemini.google.com/share/99598ee7dd80"
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
try:
    resp = urllib.request.urlopen(req).read().decode('utf-8')
    matches = re.findall(r'\[\\"([^"\]]{20,})\\"', resp)
    unique_matches = []
    for m in matches:
        m = m.replace('\\\\n', '\n').replace('\\n', '\n')
        m = bytes(m, 'utf-8').decode('unicode_escape', "ignore")
        if m not in unique_matches and len(m) > 50:
            unique_matches.append(m)
            
    for i, m in enumerate(unique_matches):
        print(f"--- MATCH {i} ---")
        print(m[:800])
        print()
except Exception as e:
    print("Error:", e)
