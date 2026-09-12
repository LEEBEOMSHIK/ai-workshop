import pytest
from pydantic import ValidationError

from ai_workshop.platform.workspaces.schemas import WorkspaceMemberPut


@pytest.mark.parametrize("field", ["read", "write", "delete"])
@pytest.mark.parametrize("value", [1, "true", None])
def test_grants_require_actual_booleans(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        WorkspaceMemberPut.model_validate(
            {
                "read": True,
                "write": False,
                "delete": False,
                "expected_revision": 0,
                field: value,
            }
        )


@pytest.mark.parametrize("write,delete", [(True, False), (False, True), (True, True)])
def test_write_or_delete_without_read_is_rejected(write: bool, delete: bool) -> None:
    with pytest.raises(ValidationError):
        WorkspaceMemberPut(read=False, write=write, delete=delete, expected_revision=0)


def test_owner_role_cannot_be_injected_into_member_request() -> None:
    with pytest.raises(ValidationError):
        WorkspaceMemberPut.model_validate(
            {
                "read": True,
                "write": True,
                "delete": True,
                "expected_revision": 1,
                "role": "owner",
            }
        )
