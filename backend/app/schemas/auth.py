import uuid
from typing import Optional
from pydantic import BaseModel, EmailStr, ConfigDict, Field
from datetime import datetime

class UserBase(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    role: Optional[str] = "user"

class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)

class UserResponse(UserBase):
    id: uuid.UUID
    is_active: bool
    created_at: datetime
    daily_question_limit: Optional[int] = None   # None = server default, 0 = unlimited
    daily_token_limit: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse

class TokenPayload(BaseModel):
    sub: Optional[str] = None

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    # Admin only. Send null to go back to the server default, 0 for unlimited.
    daily_question_limit: Optional[int] = Field(default=None, ge=0, le=1_000_000)
    daily_token_limit: Optional[int] = Field(default=None, ge=0, le=1_000_000_000)

