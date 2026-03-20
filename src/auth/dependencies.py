from typing import Annotated
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.posts.dependencies import get_db_session
from src.users.service import get_user_by_email
from src.posts.models import UserModel
from .schemas import TokenData

# 这一行告诉 FastAPI：客户端应该去哪里找 Token (login 接口的 URL)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

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
