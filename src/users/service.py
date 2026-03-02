from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from . import schemas
from src.posts import models
from src.posts.utils import get_password_hash
from fastapi import HTTPException, status


async def get_user(db:AsyncSession,user_id:int) -> models.UserModel:
    result = await db.execute(select(models.UserModel).where(models.UserModel.id == user_id))#按照id获取单个用户
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail="User not found")
    return user

async def get_user_by_email(db:AsyncSession,email:str) -> models.UserModel:
    result = await db.execute(select(models.UserModel).where(models.UserModel.email == email))#按照email查找用户防止重复
    return result.scalar_one_or_none()

async def create_user(db:AsyncSession,user:schemas.UserCreate) -> models.UserModel:#注册
    db_user = await get_user_by_email(db,email=user.email)
    if db_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,detail="email already registered")

    hashed_password = get_password_hash(user.password)
    db_user = models.UserModel(
        username = user.username,
        email = user.email,
        hashed_password = hashed_password,
        age = user.age if user.age is not None else 0,  # 默认值满足非空约束
        phone = str(user.phone) if user.phone is not None else None
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user