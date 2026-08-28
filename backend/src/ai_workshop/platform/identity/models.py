from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from ai_workshop.platform.identity.domain import UserRole
from ai_workshop.shared.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class UserRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    normalized_email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    role: Mapped[UserRole] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
