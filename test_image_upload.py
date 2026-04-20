import requests
import io
import json

def generate_random_image():
    from PIL import Image
    import random
    
    img = Image.new('RGB', (100, 100), color = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255)))
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    return img_bytes.read()

def test_full_pipeline():
    print("1. 生成随机测试图片并上传给 /upload-image/ ...")
    try:
        img_data = generate_random_image()
    except Exception as e:
        print("Pillow模块可能不存在，正在通过网络下载占位图...")
        img_data = requests.get('https://picsum.photos/200').content
    
    files = {"file": ("test_upload.jpg", img_data, "image/jpeg")}
    upload_url = "http://localhost:8000/upload-image/"
    
    upload_resp = requests.post(upload_url, files=files)
    if upload_resp.status_code != 200:
        print("图片上传失败:", upload_resp.text)
        return
        
    res_data = upload_resp.json()
    image_url = res_data.get("url")
    img_vector = res_data.get("image_embedding")
    
    if not img_vector:
        print("未能从 API 返回的 JSON 中获取特征向量哦！")
        return
        
    print(f"✅ 上传成功！获取到特征向量维度为: {len(img_vector)}")
    print(f"生成的图片地址为 {image_url}")
    print()
    
    print("2. 发起附带图片特征向量的商品发布请求到 /items/ ...")
    item_payload = {
        "name": "测试图片商品 (带视觉向量)",
        "description": "这是大模型向量测试专用",
        "count": 5,
        "amount": 99.9,
        "is_sold": False,
        "category_id": 1,
        "tags": ["测试", "AI"],
        "image_path": image_url,
        "image_embedding": img_vector
    }
    
    token = ""
    # 注意，这里的 token 需要我们去注册。如果没有 token，测试脚本可能需要模拟一个。
    # 让我们直接使用依赖注入覆写，或者先跑跑看如果没 token 报什么错
    # items 路由需要登录，但因为我们可以通过 make_admin 拿 token

    print("请求发布商品 (由于未授权可能返回 401)")
    headers = {"Authorization": f"Bearer 123456"}
    res = requests.post("http://localhost:8000/items/", json=item_payload, headers=headers)
    print(res.status_code, res.text)
    
if __name__ == "__main__":
    test_full_pipeline()
