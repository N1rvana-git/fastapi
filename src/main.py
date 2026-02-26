from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles  # 引入静态文件处理
from src.posts.router import router as posts_router
from src.posts import models
from src.config import settings
from health.router import router as health_router
from src.users.router import router as users_router
from src.auth.router import router as auth_router  # 新增
import os
from pathlib import Path

app = FastAPI(title=settings.APP_NAME)

BASE_DIR = Path(__file__).resolve().parent.parent

# 确保静态目录存在
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"

if not UPLOAD_DIR.exists():
    UPLOAD_DIR.mkdir()

if not STATIC_DIR.exists():
    STATIC_DIR.mkdir()

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

app.include_router(health_router)
app.include_router(auth_router)  # 注册认证路由
app.include_router(posts_router)
app.include_router(users_router)

@app.get("/")
async def read_root():
    return {"message": "Welcome to my practice","环境":settings.ENVIRONMENT}
