"""Synthetic geometry; no model, network, database, or company-specific rules."""

import copy
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import JsonValue

from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    Capture,
    JsonObject,
    content,
    digest,
    encode,
    message,
    object_value,
    parse_object,
)
from ai_workshop.labs.rag.evaluation.offline_layout_candidate import (
    prepare_layout_candidate,
    verify_layout_candidate,
)


def payload(company: str = "합성 장비센터", rule: str = "접수 후 9주") -> JsonObject:
    texts = ["항목", company, "교체 일정", rule, "적용 대상", "등록 장비"]
    units: list[JsonValue] = []
    offset = 0
    for index, text in enumerate(texts):
        column, row = index % 2, index // 2
        units.append({
            "evidence_id": str(UUID(int=index + 1)), "text": text,
            "bbox": [column * 100, row * 30, column * 100 + 80, row * 30 + 15],
            "char_range": [offset, offset + len(text)], "ordinal": index,
        })
        offset += len(text)
    # A separate two-column footer must not invalidate or join the actual grid.
    units.extend([
        {"evidence_id": str(UUID(int=7)), "text": "주석: 실제 상황에 따라 달라짐",
         "bbox": [0, 120, 180, 135], "char_range": [offset, offset + 20], "ordinal": 6},
        {"evidence_id": str(UUID(int=8)), "text": "공개 합성 자료",
         "bbox": [0, 300, 80, 315], "char_range": [offset + 20, offset + 30], "ordinal": 7},
        {"evidence_id": str(UUID(int=9)), "text": "2/3",
         "bbox": [400, 300, 480, 315], "char_range": [offset + 30, offset + 33], "ordinal": 8},
    ])
    return {
        "schema_version": 2, "question": f"{company} 교체 일정은?",
        "resolved_query": f"{company} 교체 일정은?", "history": [],
        "evidence_format_notice": "원문과 인용 ID를 보존한다.",
        "evidence_sources": [{"page": 2, "source_kind": "pdf_page", "source_part": None,
                              "table_cell": None, "section_path": []}],
        "evidence_blocks": [{"source_ref": 0, "fragments": units}],
    }


def units(value: JsonObject) -> list[JsonObject]:
    blocks = cast(list[JsonValue], value["evidence_blocks"])
    return [object_value(v) for v in cast(list[JsonValue], object_value(blocks[0])["fragments"])]


def capture(value: JsonObject | None = None) -> Capture:
    raw = encode({"messages": [{"role": "system", "content": "원문으로 답하고 JSON만 반환."},
                               {"role": "user", "content": encode(value or payload())}],
                  "max_tokens": 240, "temperature": 0, "response_format": {"type": "json_object"}})
    return Capture(run_id=UUID(int=10), attempt_id=UUID(int=11), execution_id=UUID(int=12),
                   kind="synthetic_fixture", request_json=raw, sha256=digest(raw),
                   body_bytes=len(raw.encode()), body_characters=len(raw),
                   status="response_received",
                   content_status="complete", model="合成", provider="local_openai_compatible",
                   dialect="ollama", model_version=1, profile_version=1, prompt_ref="fixture")


def test_prepare_adds_only_observed_id_matrix_and_preserves_every_original_value() -> None:
    source = capture()
    candidate = prepare_layout_candidate(source)
    assert candidate.execution_status == "not_run"
    assert candidate.preparation_status == "prepared"
    assert candidate.condition == "D"
    assert candidate.grid_count == 1
    original, revised = parse_object(source.request_json), parse_object(candidate.request_json)
    original_payload, revised_payload = parse_object(content(original, 1)), parse_object(
        content(revised, 1))
    hints = object_value(revised_payload.pop("layout_hints"))
    assert hints["semantic_roles"] == "not_assigned"
    assert hints["coverage"] == "selected_fragments_only"
    assert hints["grids"] == [{"source_ref": 0, "rows": [
        [str(UUID(int=1)), str(UUID(int=2))], [str(UUID(int=3)), str(UUID(int=4))],
        [str(UUID(int=5)), str(UUID(int=6))],
    ]}]
    assert original_payload == revised_payload
    message(revised, 1)["content"] = content(original, 1)
    assert revised == original
    verify_layout_candidate(source, candidate)
    assert source == capture()


@pytest.mark.parametrize("company,rule", [("서쪽 도서관", "목요일에만 대여"),
                                         ("NORTH-73", "온도 18% 이하면 보류")])
def test_no_answer_keywords_or_header_roles_are_inferred(company: str, rule: str) -> None:
    source = capture(payload(company, rule))
    candidate = prepare_layout_candidate(source)
    p = parse_object(content(parse_object(candidate.request_json), 1))
    hints = encode(p["layout_hints"])
    assert company not in hints and rule not in hints
    assert "header" not in object_value(p["layout_hints"])
    assert candidate.grid_count == 1


@pytest.mark.parametrize("mutation", ["missing_bbox", "overlap", "reverse", "ordinal_reverse",
                                      "char_overlap", "duplicate_ordinal", "vertical_overlap",
                                      "infinite_bbox", "bool_bbox", "missing_page", "ocr",
                                      "cell_coordinates"])
def test_ambiguous_geometry_retains_byte_exact_input_without_a_hint(mutation: str) -> None:
    p = payload()
    u = units(p)
    source_context = object_value(cast(list[JsonValue], p["evidence_sources"])[0])
    if mutation == "missing_bbox":
        u[0]["bbox"] = None
    elif mutation == "overlap":
        u[1]["bbox"] = [70, 0, 160, 15]
    elif mutation == "reverse":
        object_value(cast(list[JsonValue], p["evidence_blocks"])[0])["fragments"] = cast(
            list[JsonValue], list(reversed(u)))
    elif mutation == "ordinal_reverse":
        u[2]["ordinal"] = 0
    elif mutation == "char_overlap":
        u[2]["char_range"] = [1, 10]
    elif mutation == "duplicate_ordinal":
        u[1]["ordinal"] = 0
    elif mutation == "vertical_overlap":
        u[2]["bbox"] = [0, 10, 80, 25]
        u[3]["bbox"] = [100, 10, 180, 25]
    elif mutation == "infinite_bbox":
        # JSON itself rejects nonfinite values; huge finite values must not overflow math.
        u[0]["bbox"] = [0, 0, 1e308, 15]
    elif mutation == "bool_bbox":
        u[0]["bbox"] = [False, 0, 80, 15]
    elif mutation == "missing_page":
        source_context["page"] = None
    elif mutation == "ocr":
        source_context["source_kind"] = "ocr_image"
    else:
        source_context["table_cell"] = {"row": 0, "column": 0}
    source = capture(p)
    c = prepare_layout_candidate(source)
    assert c.preparation_status == "no_supported_grid"
    assert c.grid_count == 0
    assert c.request_json == source.request_json
    assert c.diff == ""


def test_source_boundaries_and_single_rows_are_never_combined() -> None:
    p = payload()
    original_units = units(p)
    source = object_value(cast(list[JsonValue], p["evidence_sources"])[0])
    p["evidence_sources"] = [copy.deepcopy(source) for _ in range(3)]
    p["evidence_blocks"] = [{"source_ref": i, "fragments": cast(list[JsonValue],
                            original_units[i * 2:i * 2 + 2])} for i in range(3)]
    c = prepare_layout_candidate(capture(p))
    assert c.preparation_status == "no_supported_grid"


def test_offsets_may_have_gaps_but_are_never_repaired_or_added() -> None:
    p = payload()
    for i, unit in enumerate(units(p)):
        unit["ordinal"] = i * 2
    c = prepare_layout_candidate(capture(p))
    assert c.grid_count == 1
    assert parse_object(content(parse_object(c.request_json), 1))["evidence_blocks"] == p[
        "evidence_blocks"]


def test_reappearing_source_is_ambiguous_even_if_first_run_looks_like_a_grid() -> None:
    p = payload()
    original_units = units(p)
    sources = cast(list[JsonValue], p["evidence_sources"])
    sources.append(copy.deepcopy(sources[0]))
    p["evidence_blocks"] = [
        {"source_ref": 0, "fragments": cast(list[JsonValue], original_units[:6])},
        {"source_ref": 1, "fragments": cast(list[JsonValue], original_units[6:8])},
        {"source_ref": 0, "fragments": cast(list[JsonValue], original_units[8:])},
    ]
    assert prepare_layout_candidate(capture(p)).grid_count == 0


def test_translation_and_scale_preserve_matrix_but_near_alignment_is_not_repaired() -> None:
    p = payload()
    for unit in units(p):
        unit['bbox'] = cast(list[JsonValue], [v * 2 + 17 for v in
                                            cast(list[float], unit['bbox'])])
    assert prepare_layout_candidate(capture(p)).grid_count == 1
    # Every row has a distinct origin: do not silently round to a shared column.
    for i, unit in enumerate(units(p)[:6]):
        box = cast(list[float], unit['bbox'])
        box[0] += (i // 2) * .01
    assert prepare_layout_candidate(capture(p)).grid_count == 0


@pytest.mark.parametrize("mutation", ["text", "rule_injection", "hint", "system", "temperature"])
def test_verifier_rejects_tampering_even_with_recomputed_hash(mutation: str) -> None:
    source = capture()
    c = prepare_layout_candidate(source)
    b = parse_object(c.request_json)
    p = parse_object(content(b, 1))
    if mutation == "text":
        units(p)[0]["text"] = "허위 원문"
    elif mutation == "rule_injection":
        p["expected_answer"] = "정답 주입"
    elif mutation == "hint":
        object_value(p["layout_hints"])["grids"] = []
    elif mutation == "system":
        message(b, 0)["content"] = "변경한 지침"
    else:
        b["temperature"] = 1
    message(b, 1)["content"] = encode(p)
    raw = encode(b)
    with pytest.raises(ValueError):
        verify_layout_candidate(source, c.model_copy(update={"request_json": raw,
            "sha256": digest(raw), "body_bytes": len(raw.encode())}))


def test_incomplete_capture_and_duplicate_id_are_rejected() -> None:
    with pytest.raises(ValueError):
        prepare_layout_candidate(capture().model_copy(update={"content_status": "omitted"}))
    p = payload()
    units(p)[1]["evidence_id"] = units(p)[0]["evidence_id"]
    with pytest.raises(ValueError):
        prepare_layout_candidate(capture(p))


def test_standalone_report_escapes_source_and_refuses_existing_output(tmp_path: Path) -> None:
    from ai_workshop.labs.rag.evaluation.offline_layout_report import write_layout_report

    source = capture(payload("<script>alert(1)</script>", "규칙 없음"))
    output = tmp_path / "report"
    write_layout_report((source,), output)
    page = (output / "index.html").read_text('utf-8')
    assert '<script>' not in page
    assert '&lt;script&gt;' in page
    assert '미실행' in page
    assert 'default-src' in page
    with pytest.raises(FileExistsError):
        write_layout_report((source,), output)
