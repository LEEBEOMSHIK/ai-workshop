from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from ai_workshop.platform.identity import api as identity_api
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.errors import register_error_handlers


def make_user(role: UserRole) -> User:
    return User(
        id=uuid4(),
        display_name=role.value.title(),
        email=f"{role.value}@example.com",
        normalized_email=f"{role.value}@example.com",
        password_hash="hash",
        role=role,
    )


def guarded_app(user: User) -> FastAPI:
    application = FastAPI()
    register_error_handlers(application)

    @application.get("/owner")
    async def owner_only(
        current_user: Annotated[User, Depends(identity_api.require_owner)],
    ) -> dict[str, str]:
        return {"user_id": str(current_user.id)}

    application.dependency_overrides[identity_api.get_current_user] = lambda: user
    return application


def test_owner_guard_allows_owner() -> None:
    owner = make_user(UserRole.OWNER)

    with TestClient(guarded_app(owner)) as client:
        response = client.get("/owner")

    assert response.status_code == 200
    assert response.json() == {"user_id": str(owner.id)}


def test_owner_guard_rejects_member_with_error_envelope() -> None:
    member_role = UserRole("member")
    member = make_user(member_role)

    with TestClient(guarded_app(member)) as client:
        response = client.get("/owner")

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "owner_required"
    assert response.json()["error"]["message"] == "Owner access is required."
