from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings
from ai_workshop.platform.assets.service import get_asset_upload_coordinator
from ai_workshop.shared.errors import AppError


@pytest.mark.parametrize(
    "partial",
    [
        {"original_store_id": "originals"},
        {"original_store_binding_id": uuid4()},
    ],
)
def test_original_binding_settings_must_be_paired(partial):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, secret_key="test-secret-for-original-ownership", **partial)


def test_production_upload_composition_has_no_untracked_fallback():
    settings = Settings(_env_file=None, secret_key="test-secret-for-original-ownership")
    with pytest.raises(AppError) as exc:
        get_asset_upload_coordinator(
            assets=AsyncMock(),
            jobs=AsyncMock(),
            session=AsyncMock(spec=AsyncSession),
            settings=settings,
        )
    assert exc.value.code == "original_upload_unavailable"
    assert exc.value.status_code == 503
