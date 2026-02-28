from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os

from src.posts.router import router as posts_router
from src.config import settings
from health.router import router as health_router
from src.users.router import router as users_router
from src.auth.router import router as auth_router

app = FastAPI(title="我的全栈二手平台")  # 或者 title=settings.APP_NAME

# 1. 配置跨域通行证 (CORS) - 这一步非常重要，必须放在最前面
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True, # 允许携带 cookie
    allow_methods=["*"],  # 允许所有 HTTP 方法
    allow_headers=["*"],  # 允许所有 HTTP 头
)

# 2. 准备静态文件目录
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
STATIC_DIR = BASE_DIR / "static"

if not UPLOAD_DIR.exists():
    UPLOAD_DIR.mkdir()

if not STATIC_DIR.exists():
    STATIC_DIR.mkdir()

# 3. 挂载静态文件目录 (用于访问图片)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# 4. 注册路由
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(posts_router) # posts_router 内部已经定义了 prefix="/items"，所以这里不需要再加
app.include_router(users_router)

@app.get("/")
async def read_root():
    return {"message": "Welcome to my practice", "环境": settings.ENVIRONMENT}
