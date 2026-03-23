from pydantic import BaseModel,ConfigDict, EmailStr
from typing import Union, Optional

class UserCreate(BaseModel):
    username: str
    password: str
    email: EmailStr
    age: Union[int,None] = None
    phone: Union[str,None] = None
    role: Optional[str] = "user"

class UserPublic(BaseModel):
    id: int
    username: str
    email: str
    age: Union[int,None] = None
    phone: Union[str,None] = None
    role: str = "user"
    model_config = ConfigDict(from_attributes=True)
