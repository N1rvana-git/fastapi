import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select
from src.posts.models import UserModel
from src.posts.utils import verify_password

DATABASE_URL = 'postgresql+asyncpg://myuser:mypassword@db:5432/mydb'
engine = create_async_engine(DATABASE_URL)
SessionLocal = sessionmaker(engine, class_=AsyncSession)

async def check():
    async with SessionLocal() as session:
        result = await session.execute(select(UserModel))
        users = result.scalars().all()
        for row in users:
            is_valid = verify_password('my_password_123', row.hashed_password)
            print(f'Email: {row.email}, is_my_password_123: {is_valid}')
            is_valid2 = verify_password('string', row.hashed_password)
            print(f'Email: {row.email}, is_string: {is_valid2}')

asyncio.run(check())
