#区分“数据库表模型”（内部结构）和“API 模式”（外部合同）。
#定义数据表
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, Table, Text, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from src.database import Base
from pgvector.sqlalchemy import Vector
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

    is_sold = Column(Boolean, default=False)  # 新增：是否已售出

    embedding = Column(Vector(1024))  # 新增：商品描述的向量表示

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

#新增：AI 管家永久记忆表
class AIChatRecord(Base):
    __tablename__ = "ai_chat_records"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(String, nullable=False)  # "user" 或 "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone = True),server_default=func.now())

# 🛒 电商核心：订单状态机表
class OrderModel(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    buyer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    item_id = Column(Integer, ForeignKey("item.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(20), default="pending", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # 建立 ORM 关系映射，方便我们写 Python 代码时直接一点就能获取到商品和买家信息
    buyer = relationship("UserModel")
    item = relationship("ItemModel")