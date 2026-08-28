from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from ai_workshop.platform.identity.domain import User, UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    display_name: str
    email: str
    role: UserRole

    @classmethod
    def from_domain(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            display_name=user.display_name,
            email=user.email,
            role=user.role,
        )
