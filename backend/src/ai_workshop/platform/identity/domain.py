from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID, uuid4


class UserRole(StrEnum):
    OWNER = "owner"


def normalize_email(email: str) -> str:
    return email.strip().casefold()


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    display_name: str
    email: str
    normalized_email: str
    password_hash: str
    role: UserRole
    is_active: bool = True

    @classmethod
    def create_owner(
        cls,
        *,
        display_name: str,
        email: str,
        password_hash: str,
    ) -> "User":
        clean_email = email.strip()
        return cls(
            id=uuid4(),
            display_name=display_name.strip(),
            email=clean_email,
            normalized_email=normalize_email(clean_email),
            password_hash=password_hash,
            role=UserRole.OWNER,
        )
