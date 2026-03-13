#核心业务逻辑
from .schemas import ItemCreate, ItemUpdate
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.exc import IntegrityError
from . import schemas
from . import models
from .utils import get_password_hash

async def create_item(db: AsyncSession, item: schemas.ItemCreate, owner_id: int) -> models.ItemModel:
    """创建物品，自动关联owner_id"""
    item_data = item.model_dump(exclude={"tag_ids"})  # 先排除标签 ID，后面单独处理
    db_item = models.ItemModel(**item_data, owner_id=owner_id)

    if item.tag_ids:
        tags = await get_tags_by_ids(db, item.tag_ids)
        db_item.tags = list(tags)
    
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

async def get_item(db: AsyncSession, item_id: int) -> models.ItemModel | None:
    """根据 ID 查找物品"""
    result = await db.execute(select(models.ItemModel).where(models.ItemModel.id == item_id))
    return result.scalars().one_or_none()

async def delete_item(db: AsyncSession, item: models.ItemModel):
    """删除物品"""
    await db.delete(item)
    await db.commit()

async def update_item(db: AsyncSession, db_item: models.ItemModel, item_update: schemas.ItemUpdate):
    """更新物品逻辑"""
    # 只提取用户真正传了的字段
    update_data = item_update.model_dump(exclude_unset=True,exclude={"tag_ids"})
    
    # 遍历字典，更新数据库对象
    for key, value in update_data.items():
        setattr(db_item, key, value)

    # 检查是否需要更新标签
    if item_update.tag_ids is not None:
        tags = await get_tags_by_ids(db, item_update.tag_ids)
        db_item.tags = list(tags)

    # 如果更新了库存，自动同步 is_sold 状态
    if hasattr(db_item, "inventory"):
        if db_item.inventory > 0:
            db_item.is_sold = False
        else:
            db_item.is_sold = True

    # 提交保存
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item

async def get_tag_by_name(db: AsyncSession, name: str):
    query = select(models.item_TagModel).where(models.item_TagModel.name == name)
    result = await db.execute(query)
    return result.scalars().first()

async def create_tag(db: AsyncSession, tag_name: str) -> models.item_TagModel:
    existing_tag = await get_tag_by_name(db, tag_name)
    if existing_tag:
        return existing_tag
    
    try:
        db_tag = models.item_TagModel(name=tag_name)#创建新标签
        db.add(db_tag)
        await db.commit()
        await db.refresh(db_tag)
        return db_tag
    except IntegrityError:
        await db.rollback()
        # If create failed due to race condition, return existing
        existing = await get_tag_by_name(db, tag_name)
        if existing:
            return existing
        raise # Re-raise if it's some other integrity error

async def get_tags_by_ids(db: AsyncSession, tag_ids: list[int]):
    if not tag_ids:
        return []
    result = await db.execute(select(models.item_TagModel).where(models.item_TagModel.id.in_(tag_ids)))
    return result.scalars().all()
