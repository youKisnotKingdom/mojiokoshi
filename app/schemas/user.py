from datetime import datetime

from pydantic import BaseModel, Field

from app.models.user import UserRole


class UserBase(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)
    role: UserRole = UserRole.USER


class UserCreate(UserBase):
    password: str = Field(..., min_length=4, max_length=100)


class UserUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=100)
    role: UserRole | None = None
    is_active: bool | None = None


class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=4, max_length=100)


class UserResponse(UserBase):
    id: int
    user_id: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    user_id: str = Field(..., pattern=r"^\d{6}$")
    password: str


class LoginResponse(BaseModel):
    message: str
    user: UserResponse
