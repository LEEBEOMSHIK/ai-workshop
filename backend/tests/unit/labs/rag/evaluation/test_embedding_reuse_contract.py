import pytest
from pydantic import ValidationError

from ai_workshop.config import Settings
from ai_workshop.labs.rag.executions.domain import OperationTiming, StageObservation


def test_result_reuse_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AI_WORKSHOP_FROZEN_EVALUATION_EMBEDDING_CACHE_BYTES", raising=False)
    settings = Settings(secret_key="x" * 32, _env_file=None)
    assert settings.frozen_evaluation_embedding_cache_bytes == 0


@pytest.mark.parametrize("limit", [0, 16 * 1024 * 1024, 64 * 1024 * 1024])
def test_result_reuse_limit_accepts_bounded_integer_bytes(limit):
    settings = Settings(
        secret_key="x" * 32, _env_file=None, frozen_evaluation_embedding_cache_bytes=limit
    )
    assert settings.frozen_evaluation_embedding_cache_bytes == limit


@pytest.mark.parametrize("invalid", [True, False, 1.5, -1, 64 * 1024 * 1024 + 1, "1.0", "-1"])
def test_result_reuse_limit_rejects_invalid_values(invalid):
    with pytest.raises(ValidationError):
        Settings(
            secret_key="x" * 32, _env_file=None, frozen_evaluation_embedding_cache_bytes=invalid
        )


def test_result_reuse_limit_reads_decimal_environment_bytes(monkeypatch):
    monkeypatch.setenv("AI_WORKSHOP_FROZEN_EVALUATION_EMBEDDING_CACHE_BYTES", "16777216")
    settings = Settings(secret_key="x" * 32, _env_file=None)
    assert settings.frozen_evaluation_embedding_cache_bytes == 16777216


def test_result_reuse_timing_round_trips_without_input_content():
    timing = OperationTiming.model_validate({
        "name": "embedding.result_reuse", "duration_ms": 0.25, "calls": 2,
        "failures": 0, "items": 3, "reused_items": 3,
    })
    stage = StageObservation(stage="selection", state="completed", operations=[timing])
    restored = StageObservation.model_validate_json(stage.model_dump_json())
    assert restored == stage
    assert restored.operations == [timing]
    assert set(timing.model_dump()) == {
        "name", "duration_ms", "calls", "failures", "items", "reused_items",
    }
