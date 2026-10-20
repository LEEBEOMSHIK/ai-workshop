import pytest

from ai_workshop.labs.rag.search.pipeline import _safe_generation_error


@pytest.mark.parametrize(
    "code,status",
    [
        ("provider_busy", 503),
        ("provider_input_too_large", 422),
    ],
)
def test_local_provider_errors_keep_actionable_codes(code: str, status: int) -> None:
    error = _safe_generation_error(code)
    assert error.code == code
    assert error.status_code == status
