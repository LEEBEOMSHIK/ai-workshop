from copy import deepcopy

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.comparisons.schemas import ComparisonImport
from tests.unit.labs.rag.comparisons.support import payload


def test_valid_report_preserves_null_and_original_answers() -> None:
    report = ComparisonImport.model_validate(payload())
    assert report.requests[0].first_token_seconds is None
    assert report.requests[0].answer == "접수일 기준 4영업일 뒤 지급합니다."
    assert report.estimated_total_usd is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "12.0"])
def test_reject_invalid_durations(value: object) -> None:
    data = payload()
    data["requests"][0]["duration_seconds"] = value
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)


@pytest.mark.parametrize(
    "field,value", [("response_id", "resp_secret"), ("api_key", "secret"), ("raw_response", {})]
)
def test_unknown_provider_fields_are_rejected(field: str, value: object) -> None:
    data = payload()
    data["requests"][0][field] = value
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)


def test_citations_must_reference_existing_evidence() -> None:
    data = payload()
    data["requests"][0]["citations"][0]["evidence_refs"] = ["e999"]
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)


def test_report_rejects_duplicate_order_and_refs() -> None:
    data = payload()
    data["requests"][1]["sequence"] = 1
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)
    data = payload()
    data["evidence"].append(deepcopy(data["evidence"][0]))
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)


def test_rejects_cost_total_mismatch_and_numeric_money() -> None:
    data = payload()
    data["requests"][0].update(estimated_cost_usd="0.000667", cost_status="usage_estimate")
    data.update(estimated_total_usd="0.000668", billing_status="not_reconciled")
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)
    data["estimated_total_usd"] = 0.000667
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)


def test_cost_is_exact_and_unknown_billing_stays_null() -> None:
    data = payload()
    data["requests"][0].update(estimated_cost_usd="0.000667", cost_status="usage_estimate")
    data.update(estimated_total_usd="0.000667", billing_status="not_reconciled")
    report = ComparisonImport.model_validate(data)
    assert report.estimated_total_usd == "0.000667"
    assert report.actual_billed_total_usd is None


def test_completed_at_requires_timezone() -> None:
    data = payload()
    data["completed_at"] = "2026-10-29T02:38:39"
    with pytest.raises(ValidationError):
        ComparisonImport.model_validate(data)
