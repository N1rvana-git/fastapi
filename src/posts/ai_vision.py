# src/posts/ai_vision.py
import torch
import io
from PIL import Image
from transformers import ChineseCLIPProcessor, ChineseCLIPModel

print("🚀 [AI Vision] 正在加载阿里 CN-CLIP 多模态大模型...")
print("⏳ (首次启动需要下载约 600MB 模型权重，请耐心等待)")

model_name = "OFA-Sys/chinese-clip-vit-base-patch16"
# 初始化处理器和模型
processor = ChineseCLIPProcessor.from_pretrained(model_name)
model = ChineseCLIPModel.from_pretrained(model_name)
model.eval() # 极其重要：锁定模型为推理模式，防止显存泄漏

# 自动硬件加速：有 GPU 跑 GPU，没 GPU 跑 CPU
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
print(f"✅ [AI Vision] 视觉大脑加载完成！当前运行设备: {device}")

def get_image_embedding(image_bytes: bytes) -> list[float]:
    """将物理图片转化为 512 维的数学空间特征向量"""
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    
    # 预处理并丢进模型
    inputs = processor(images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        image_features = model.get_image_features(**inputs)
    
    # 🌟 架构师细节：特征归一化 (L2 Norm)，能让后面的余弦相似度计算极度精准！
    image_features = image_features / image_features.norm(p=2, dim=-1, keepdim=True)
    return image_features.squeeze().cpu().tolist()

def get_text_embedding(text: str) -> list[float]:
    """跨模态魔法：将纯文字转化为和图片完全同频的 512 维特征向量！"""
    inputs = processor(text=[text], padding=True, return_tensors="pt").to(device)
    with torch.no_grad():
        text_features = model.get_text_features(**inputs)
        
    text_features = text_features / text_features.norm(p=2, dim=-1, keepdim=True)
    return text_features.squeeze().cpu().tolist()
    return text_features.squeeze().cpu().tolist()