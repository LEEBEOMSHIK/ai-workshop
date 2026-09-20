import pytest

from tests.integration.platform.assets.original_upload_support import (
    require_explicit_original_test_database,
)


@pytest.mark.parametrize("missing", ["AI_WORKSHOP_ENVIRONMENT", "AI_WORKSHOP_DATABASE_URL"])
def test_original_integration_requires_explicit_test_environment(monkeypatch, missing):
    monkeypatch.setenv("AI_WORKSHOP_ENVIRONMENT", "test")
    monkeypatch.setenv("AI_WORKSHOP_DATABASE_URL", "postgresql://synthetic@127.0.0.1/postgres")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match="explicit_original_test_database_required"):
        require_explicit_original_test_database()
