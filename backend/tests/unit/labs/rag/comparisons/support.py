from copy import deepcopy


def payload() -> dict[str, object]:
    first = {
        "sequence": 1,
        "provider": "local",
        "model": "synthetic-model",
        "repetition": 1,
        "condition": "first",
        "duration_seconds": 12.0,
        "first_token_seconds": None,
        "native_timing": {
            "load_seconds": 1.0,
            "input_seconds": 9.0,
            "output_seconds": 1.5,
            "total_seconds": 11.8,
        },
        "usage": {
            "input_tokens": 100,
            "output_tokens": 10,
            "cached_input_tokens": None,
            "cache_write_tokens": None,
            "reasoning_tokens": None,
        },
        "estimated_cost_usd": None,
        "actual_billed_cost_usd": None,
        "cost_status": "not_applicable",
        "pricing_basis": None,
        "answer": "접수일 기준 4영업일 뒤 지급합니다.",
        "citations": [{"claim_index": 0, "evidence_refs": ["e1"]}],
        "quality": {
            "schema_valid": True,
            "citation_validator_passed": True,
            "baseline_answer_equal": True,
            "baseline_citations_equal": True,
            "semantic_review": "passed",
            "review_summary": "공개 합성 원문 대조",
            "criteria": [
                {
                    "key": "general_rule",
                    "label": "일반 규칙",
                    "status": "met",
                    "explanation": "4영업일을 설명합니다.",
                }
            ],
        },
    }
    second = deepcopy(first)
    second.update(
        sequence=2, repetition=2, condition="repeat", duration_seconds=2.0, native_timing=None
    )
    return {
        "schema_version": 1,
        "source_key": "synthetic-comparison-v1",
        "title": "합성 모델 비교",
        "question": "언제 지급되나요?",
        "completed_at": "2026-10-29T02:38:39Z",
        "unique_question_count": 1,
        "measurement_scope": "complete_nonstream_generation_response",
        "source_result_sha256": "1" * 64,
        "source_ledger_sha256": "2" * 64,
        "source_input_sha256": "3" * 64,
        "controls": ["같은 공개 질문과 근거"],
        "evidence": [
            {
                "ref": "e1",
                "evidence_id": "10000000-0000-0000-0000-000000000001",
                "document_id": "10000000-0000-0000-0000-000000000002",
                "asset_version_id": "10000000-0000-0000-0000-000000000003",
                "projection_id": "10000000-0000-0000-0000-000000000004",
                "index_build_id": "10000000-0000-0000-0000-000000000005",
                "retrieval_chunk_id": "10000000-0000-0000-0000-000000000006",
                "element_id": "10000000-0000-0000-0000-000000000007",
                "title": "합성 문서",
                "text": "접수일 T+4 영업일",
                "ordinal": 0,
                "page": 2,
                "char_start": 0,
                "char_end": 12,
                "bbox": [10.0, 20.0, 120.0, 30.0],
                "source_kind": "pdf_page",
            }
        ],
        "requests": [first, second],
        "estimated_total_usd": None,
        "actual_billed_total_usd": None,
        "billing_status": "not_applicable",
        "analysis": [{"title": "분석", "body": "동일 질문 반복의 저장 관측입니다."}],
        "limitations": ["고유 질문 한 건으로 일반 정확도를 확정하지 않습니다."],
    }
