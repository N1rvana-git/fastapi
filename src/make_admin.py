import asyncio
from sqlalchemy import update
from src.database import AsyncSessionLocal

from src.posts.models import UserModel

async def upgrade_to_admin(email: str):
    async with AsyncSessionLocal() as session:
        # 查找用户
        await session.execute(
            update(UserModel)
            .where(UserModel.email == email)
            .values(role="admin")
        )
        await session.commit()
        print(f"🎉 搞定！用户 {email} 已经黄袍加身，成为超级管理员！")

if __name__ == "__main__":
    # 这里填入你刚才登录测试用的邮箱账号
    asyncio.run(upgrade_to_admin("admin@qq.com"))