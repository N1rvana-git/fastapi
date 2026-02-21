from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy import MetaData
from src.config import settings

POSTGRES_INDEXES_NAMING_CONVENTION = {#命名约定
    "ix":"%(column_0_label)s_idx",
    "uq":"%(table_name)s_%(column_0_label)s_key",
    "ck":"%(table_name)s_%(column_0_label)s_check",
    "fk":"%(table_name)s_%(column_0_label)s_fkey",
    "pk":"%(table_name)s_%(column_0_label)s_pkey",
}
#创建metadata实例并应用约定
metadata_obj = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)

#通过继承 Base，SQLAlchemy 的"声明式系统"(DeclarativeBase)
#就能自动"发现" UserModel 和 ItemModel，并知道它们是需要被 Alembic 管理的数据库表。
#Base类使用带约定的metadata
class Base(DeclarativeBase):
    metadata = metadata_obj

engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)