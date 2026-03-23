from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from src.posts.dependencies import get_db_session
from src.users.service import get_user_by_email
from src.posts.utils import verify_password
from src.config import settings
from . import schemas, utils

router = APIRouter(tags=["authentication"])

@router.post("/token", response_model=schemas.Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db_session)
):
    # 1. 验证用户是否存在
    user = await get_user_by_email(db, email=form_data.username)
    
    # 2. 验证密码是否正确
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # 3. 生成 Token
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = utils.create_access_token(
        data={
            "sub": user.email,
            "role": user.role
            },
        expires_delta=access_token_expires
    )
    
    # 4. 返回 Token
    return {"access_token": access_token, "token_type": "bearer"}
