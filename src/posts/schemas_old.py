from pydantic import BaseModel, field_validator, ConfigDict
from typing import Union

#定义输入/输出的数据类型
class Item(BaseModel):
    name: str
    price: float
    is_offer: Union[bool,None]=None
    model_config = ConfigDict(
        from_attributes=True
    )#from_attributes=True 是连接你的“内部数据库模型” (models.py)
    # 和“外部 API 合同” (schemas.py) 之间的桥梁。
    # 它允许你的 Pydantic 响应模型，能直接从你的 SQLAlchemy ORM 对象中“读取”数据。

class User(BaseModel):
    username: str
    email: Union[str,None]=None
    password: str
    @field_validator("password")#这个装饰器，把它“注册”到了 Pydantic 模型的**“验证生命周期”**中。
    @classmethod
    def validate_password_strength(cls, v:str) -> str:#实现自定义业务规则
        if len(v)<8:
            raise ValueError("Password must be at least 8 characters long")
        return v

class UpdateItemResponse(BaseModel):
    item_id: int
    username: str
    email: Union[str,None]=None

class CreateItemWithUserRequest(BaseModel):
    """组合请求：同时创建物品和可选的用户"""
    item: Item
    user: Union[User, None] = None

class CreateItemWithUserResponse(BaseModel):
    """组合响应：返回物品字段 + 用户名"""
    name: str
    price: float
    is_offer: Union[bool, None] = None
    username: Union[str, None] = None
    
    model_config = ConfigDict(from_attributes=True)

class ItemBase(BaseModel):
    name: str
    price: float
    is_offer: Union[bool, None] = None
    image_url: Union[str, None] = None