from pydantic import BaseModel, field_validator, ConfigDict
from typing import Union, List

class TagBase(BaseModel):
    name: str

class TagCreate(TagBase):
    name: str

class Tag(TagBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# 定义基础物品字段（大家都有的）
class ItemBase(BaseModel):
    name: str
    price: float
    is_offer: Union[bool, None] = None
    image_path: Union[str, None] = None  # 新增图片路径字段
    

# 专门用于"创建"的模型
class ItemCreate(ItemBase):
    tag_ids: List[int] = [] # 新增：创建物品时可以直接指定标签 ID 列表

# 专门用于"更新"的模型（所有字段都是可选的）
class ItemUpdate(BaseModel):
    name: Union[str, None] = None
    price: Union[float, None] = None
    is_offer: Union[bool, None] = None
    tag_ids: Union[List[int], None] = None # 新增：更新物品时可以指定标签 ID 列表
    image_path: Union[str, None] = None
    
# 专门用于"读取/响应"的模型
class Item(ItemBase):
    id: int
    owner_id: int
    tags: List[Tag] = [] # Use Tag in response
    model_config = ConfigDict(from_attributes=True)

class User(BaseModel):
    username: str
    email: Union[str, None] = None
    password: str
    
    @field_validator("password")
    @classmethod
    def validate_password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        return v

class UpdateItemResponse(BaseModel):
    item_id: int
    username: str
    email: Union[str, None] = None

class CreateItemWithUserRequest(BaseModel):
    """组合请求：同时创建物品和可选的用户"""
    item: ItemCreate
    user: Union[User, None] = None

class CreateItemWithUserResponse(BaseModel):
    """组合响应：返回物品字段 + 用户名"""
    name: str
    price: float
    is_offer: Union[bool, None] = None
    username: Union[str, None] = None
    
    model_config = ConfigDict(from_attributes=True)
