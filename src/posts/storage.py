import os
import shutil
import asyncio
from fastapi import UploadFile

#1.定义一个“抽象”的存储提供商接口
class StorageProvider:
    async def upload(self, file: UploadFile) -> str:
        """上传文件并返回可访问的 URL"""
        raise NotImplementedError

#2.本地存储
class LocalStorageProvider(StorageProvider):
    def __init__(self, upload_dir: str = "uploads"):
        self.upload_dir = upload_dir
        if not os.path.exists(upload_dir):
            os.makedirs(upload_dir)

    async def upload(self, file: UploadFile) -> str:
        file_location = f"{self.upload_dir}/{file.filename}"
        with open(file_location, "wb+") as file_object:
            shutil.copyfileobj(file.file, file_object)
        return f"/{file_location}"
    
#3. 方案 B：模拟云原生对象存储 (如 AWS S3 / 阿里云 OSS)
class CloudStorage(StorageProvider):
    async def upload(self, file: UploadFile) -> str:
        print(f"☁️ [云存储中心] 正在将 {file.filename} 上传至云端节点...")
        # 模拟上传到云存储，返回一个假 URL
        await asyncio.sleep(2)  # 模拟网络延迟
        #模拟云端返回了一个永久有效的全球 CDN 加速网址
        fake_cloud_url = f"https://my-enterprise-bucket.s3.amazonaws.com/images/{file.filename}"
        print(f"✅ [云存储中心] 上传成功！CDN 分发地址: {fake_cloud_url}")
        return fake_cloud_url
    
#4.全局切换开关
current_storage = CloudStorage()  # 切换到云存储方案