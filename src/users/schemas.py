from pydantic import BaseModel,ConfigDict
from typing import Union

class UserCreate(BaseModel):#输入
    username: str
    password: str
    email: str
    age: Union[int,None] = None
    phone: Union[str,None] = None

class UserPublic(BaseModel):#输出
    id: int
    username: str
    email: str
    age: Union[int,None] = None
    phone: Union[str,None] = None

    model_config = ConfigDict(from_attributes=True)