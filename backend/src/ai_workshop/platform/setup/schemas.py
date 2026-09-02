from pydantic import BaseModel, EmailStr, Field


class SetupStatusResponse(BaseModel):
    setup_required: bool


class OwnerSetupRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=1024)
    password_confirmation: str = Field(min_length=12, max_length=1024)
