from fastapi import FastAPI,Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os
import time
import uuid
import logging
from src.posts.router import router as posts_router
from src.config import settings
from health.router import router as health_router
from src.users.router import router as users_router
from src.auth.router import router as auth_router

# ==========================================
# 🔦 探照灯配置：设定大厂标准的日志格式
# ==========================================
# %(asctime)s: 时间 | %(levelname)s: 级别(INFO/ERROR) | %(message)s: 具体内容
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


from src.feishu.router import router as feishu_router
app = FastAPI(title="我的全栈二手平台")  # 或者 title=settings.APP_NAME
from patch import add_exception_handler
add_exception_handler(app)
from patch import add_exception_handler
add_exception_handler(app)
app = FastAPI(title="我的全栈二手平台")
from patch import add_exception_handler
add_exception_handler(app)
from patch import add_exception_handler
add_exception_handler(app)

# ==========================================
# 🛡️ 一楼安检大厅：全局日志中间件
# ==========================================
@app.middleware("http")
async def add_trace_id_and_log(request: Request, call_next):
    trace_id = str(uuid.uuid4())[:8]  # 生成唯一的 Trace ID
    start_time = time.time()  # 记录请求开始时间

    # 在请求上下文中添加 Trace ID（可以通过 request.state 访问）
    request.state.trace_id = trace_id

    logger.info(f"🟢 [IN]  {trace_id} | 请求: {request.method} {request.url.path}")

    response = await call_next(request)

    process_time = (time.time() - start_time) * 1000 # 换算成毫秒
    logger.info(f"🔴 [OUT] {trace_id} | 状态: {response.status_code} | 耗时: {process_time:.2f} ms")
    
    # 我们甚至可以把号码牌贴在返回给用户的头上（响应头里），方便以后前端报错时报这个码！
    response.headers["X-Trace-ID"] = trace_id
    
    return response


app.include_router(feishu_router)
app.add_middleware(
    CORSMiddleware,
    # 允许访问的前端地址，注意：千万不要在网址最后加斜杠 "/"
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],  # 允许所有的请求方式 (GET, POST 等)
    allow_headers=["*"],  # 允许所有的请求头
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