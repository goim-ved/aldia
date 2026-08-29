"""Authentication and User Pydantic v2 validation schemas."""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    """Payload for user account registration."""

    email: EmailStr = Field(..., description="Valid user email address")
    password: str = Field(
        ..., min_length=8, max_length=128, description="Strong user password (min 8 characters)"
    )


class UserLogin(BaseModel):
    """Payload for user login authentication."""

    email: EmailStr = Field(..., description="User email address")
    password: str = Field(..., description="User password")


class Token(BaseModel):
    """Access token response schema."""

    access_token: str = Field(..., description="Signed JWT Bearer access token")
    token_type: str = Field(default="bearer", description="Token type")


class TokenPayload(BaseModel):
    """Decoded JWT claims payload."""

    sub: str | None = Field(default=None, description="Subject identifier (user_id)")
    exp: int | None = Field(default=None, description="Expiration timestamp (epoch)")


class UserResponse(BaseModel):
    """Public user response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="Unique user ID")
    email: EmailStr = Field(..., description="User email address")
    is_active: bool = Field(..., description="Account active status")
    created_at: datetime = Field(..., description="Timestamp when account was created")
    updated_at: datetime = Field(..., description="Timestamp when account was last modified")
