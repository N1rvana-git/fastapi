from fastapi import Depends, APIRouter, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from . import schemas
from . import service
from src.posts.dependencies import get_db_session
from src.auth.dependencies import get_current_admin_user
from src.posts.models import UserModel

router = APIRouter(
    prefix="/users",
    tags=["users"]
)

@router.get("/admin/all", response_model=List[schemas.UserPublic])
async def get_all_users_admin(
    admin_user: UserModel = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db_session)
):
    """
    【上帝视角】仅管理员可以查看系统中所有用户
    """
    result = await db.execute(select(UserModel))
    return result.scalars().all()

@router.post("/", response_model=schemas.UserPublic)
async def register_user(
        user_in: schemas.UserCreate,#调用pydantic模型进行验证注册
        db: AsyncSession = Depends(get_db_session)
):
    db_user = await service.create_user(db=db, user=user_in)
    return db_user

@router.get("/{user_id}", response_model=schemas.UserPublic)#加上装饰器，它就“活了”，变成了一个“活的”** API 端点，
# 能响应 GET 请求、处理路径参数 ({user_id})，并使用 response_model（schemas.UserPublic）来过滤响应。
async def get_user_info(
        user_id: int,
        db: AsyncSession = Depends(get_db_session)
):
    db_user = await service.get_user(db=db, user_id=user_id)
    return db_user