import pytest

from ai_workshop.labs.rag.ocr.contracts import OcrRuntimeError
from ai_workshop.worker import _rag_error


@pytest.mark.parametrize(
    "code", ["ocr_model_artifact_missing", "ocr_output_invalid", "ocr_runtime_unavailable"],
)
def test_ocr_failure_preserves_diagnostic_code_without_retry_or_raw_message(code: str) -> None:
    failure = OcrRuntimeError(code, "private provider diagnostic")

    assert _rag_error(failure) == (code, False)
