from fastapi import FastAPI
from src.posts.router import router as posts_router
from src.posts import models
from src.config import settings
from health.router import router as health_router
from src.users.router import router as users_router
from src.auth.router import router as auth_router  # 新增

app = FastAPI(title=settings.APP_NAME)

app.include_router(health_router)
app.include_router(auth_router)  # 注册认证路由
app.include_router(posts_router)
app.include_router(users_router)

@app.get("/")
async def read_root():
    return {"message": "Welcome to my practice","环境":settings.ENVIRONMENT}
