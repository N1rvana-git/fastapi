import subprocess
import json
import os

token = open("/tmp/env.sh").read().split("=")[1].strip()
headers = {"Authorization": f"Bearer {token}"}

images = [
    {"path": "test_images/apple_phone.jpg", "name": "Apple iPhone", "price": 5999.0},
    {"path": "test_images/white_shoes_1.jpg", "name": "White Shoes", "price": 299.0},
    {"path": "test_images/black_shoes.jpg", "name": "Black Shoes", "price": 319.0},
]

for img in images:
    # 1. upload image
    print(f"Uploading {img['path']}")
    cmd = f'curl -s -X POST "http://127.0.0.1:8000/items/upload-image/" -H "Authorization: Bearer {token}" -F "file=@{img["path"]}"'
    output = subprocess.check_output(cmd, shell=True)
    res = json.loads(output)
    url = res["url"]
    embedding = res["image_embedding"]
    
    # 2. create item
    print(f"Creating item {img['name']}")
    item_data = {
        "name": img['name'],
        "price": img['price'],
        "is_offer": False,
        "image_path": url,
        "image_embedding": embedding
    }
    
    with open("temp.json", "w") as f:
        json.dump(item_data, f)
        
    cmd2 = f'curl -s -X POST "http://127.0.0.1:8000/items/" -H "Authorization: Bearer {token}" -H "Content-Type: application/json" -d @temp.json'
    res2 = subprocess.check_output(cmd2, shell=True)
    print(res2.decode('utf-8')[:100] + "...")
