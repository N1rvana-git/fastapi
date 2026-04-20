import requests
from src.config import settings

response = requests.get(
    "https://api.zetatechs.com/v1/models",
    headers={"Authorization": f"Bearer {settings.API_KEy or settings.API_KEY}"}
)
data = response.json()
print("Available models:")
for model in data.get("data", []):
    print(model.get("id"))
