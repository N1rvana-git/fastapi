from pydantic_settings import BaseSettings,SettingsConfigDict
from pathlib import Path

env_path = Path(__file__).parent.parent / ".env" #path是config文件路径，src/目录-根目录-拼接虚拟环境

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=env_path,
        env_file_encoding="utf-8",
        extra="ignore" # 允许 .env 有多余字段
    )
    APP_NAME:str="默认fastapi应用"
    ENVIRONMENT:str="development"
    DATABASE_URL:str="sqlite+aiosqlite:///./test.db"# Pydantic 会自动从 .env 读取它
    
    REDIS_URL:str="redis://127.0.0.1:6379/0"

    # JWT 认证配置
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # 大模型/飞书密钥配置（统一走环境变量）
    ZHIPUAI_API_KEY: str = ""
    CHAT_API_KEY: str = ""
    API_KEY: str = "" # 中转平台的Key
    API_KEy: str = "" # 中转平台的Key (备用)
    CHAT_BASE_URL: str = "https://api.zetatechs.com/v1"
    CHAT_MODEL: str = "gemini-3-flash-preview-free"
    ZHIPU_EMBEDDING_MODEL: str = "embedding-2"
    ALLOWED_CHAT_MODELS: str = "gemini-3-flash-preview-free"
    ALLOWED_EMBEDDING_MODELS: str = "embedding-2"
    FEISHU_VERIFICATION_TOKEN: str = ""
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""

settings = Settings()