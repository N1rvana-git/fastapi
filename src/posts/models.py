#区分“数据库表模型”（内部结构）和“API 模式”（外部合同）。
#定义数据表
from sqlalchemy import Column, Integer, String,Float,Boolean,ForeignKey,Table
from sqlalchemy.orm import relationship
from src.database import Base

class ItemModel(Base):
    __tablename__ = "item"#表名
    id = Column(Integer, primary_key=True,index=True)
    name = Column(String,index=True)
    price = Column(Float)
    is_offer = Column(Boolean,default=True)
    
    # 新增图片路径字段
    image_path = Column(String, nullable=True)

    # 外键：指向 users 表的 id 列
    owner_id = Column(Integer, ForeignKey("users.id"))
    
    # 关系：反向查主人
    owner = relationship("UserModel", back_populates="items")
    # 关系：多对多查标签
    tags = relationship("item_TagModel", secondary="item_tag", back_populates="items", lazy="selectin")

class UserModel(Base):
    __tablename__ = "users"#把 Python 类映射成 PostgreSQL 表
    id = Column(Integer, primary_key=True,index=True)
    username = Column(String,index=True)
    age=Column(Integer,nullable=False)
    email = Column(String,index=True)
    phone = Column(String,index=True)
    hashed_password = Column(String)
    
    # 关系：反向查物品列表
    # cascade="all, delete-orphan" 表示：如果用户被删了，他的物品也会自动被删掉
    items = relationship("ItemModel", back_populates="owner", cascade="all, delete-orphan")

# 【新增】1. 定义关联表 (Association Table)
item_tag_association = Table(
    "item_tag",
    Base.metadata,
    Column("item_id", Integer, ForeignKey("item.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)

# 【新增】2. 定义 TagModel
class item_TagModel(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    # 与 Item 的多对多关系：通过 secondary 指定上面定义的关联表
    items = relationship("ItemModel", secondary=item_tag_association, back_populates="tags")

