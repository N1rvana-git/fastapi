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
    SECRET_KEY: str = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

settings = Settings()