from typing import Annotated, Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.posts.dependencies import get_db_session
from src.users.service import get_user_by_email
from src.posts import models
from src.posts.models import UserModel
from .schemas import TokenData

# 这一行告诉 FastAPI：客户端应该去哪里找 Token (login 接口的 URL)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: AsyncSession = Depends(get_db_session)
) -> UserModel:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # 1. 解码 Token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception
    
    # 2. 从数据库查用户
    user = await get_user_by_email(db, email=token_data.username)
    if user is None:
        raise credentials_exception
        
    return user


async def get_current_user_optional(
    token: Annotated[Optional[str], Depends(oauth2_scheme_optional)],
    db: AsyncSession = Depends(get_db_session),
) -> Optional[UserModel]:
    """可选鉴权：token 缺失或无效时返回 None，不抛 401。"""
    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
        token_data = TokenData(username=username)
    except JWTError:
        return None

    user = await get_user_by_email(db, email=token_data.username)
    return user

async def get_current_admin_user(
    current_user: Annotated[UserModel, Depends(get_current_user)]
) -> UserModel:
    """
    管理员专属门卫：不仅需要登录（get_current_user），而且 role 必须是 admin
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges",
        )
    return current_user

#超级管理员专属安检门
async def get_admin_user(current_user: models.UserModel = Depends(get_current_user)):
    """
    大厂级 RBAC 核心：
    这个函数会先自动调用 get_current_user 检查是否登录。
    如果登录了，再检查他的角色是不是 admin。
    """
    # 扫描手环芯片里的角色...
    if current_user.role != "admin":
        print(f"🚨 [警报] 普通用户 {current_user.email} 试图硬闯管理员禁区！已被拦截！")
        # 403 Forbidden 是 HTTP 协议里专门用来表示“身份没问题，但权限不够”的状态码
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="🛑 皇家禁卫军拦截：您是普通买家，没有权限使用此接口！"
        )
    
    # 只有金手环才能走到这一步！
    return current_user