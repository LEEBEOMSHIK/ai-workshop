"""Lossless transport checks with synthetic evidence; never call a model."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.documents.domain import TableCellLocation
from ai_workshop.labs.rag.generation.domain import GenerationRequest
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.openai_compatible import _generation_user_content
from tests.unit.labs.rag.generation.test_openai_compatible import evidence, schema2_profile


def restore(payload):
    identities = ("document_id", "asset_version_id", "projection_id", "chunk_id")
    restored = []
    for raw in payload["evidence"]:
        item = payload["evidence_groups"][raw["group_ref"]] | {
            key: value for key, value in raw.items() if key != "group_ref"
        }
        item |= dict(zip(identities, item["group_id"].split(":"), strict=True))
        item["context_notice"] = payload["context_notice"]
        restored.append(item)
    return restored


def request(items):
    return GenerationRequest("지급 기간?", "합성 상품의 지급 기간?", (), items,
                             schema2_profile(), "synthetic")


@pytest.mark.parametrize("schema", [1, 2])
def test_repeated_context_metadata_is_sent_once_without_losing_any_source_value(schema):
    original = tuple(replace(
        evidence(), evidence_id=UUID(int=100 + index), element_id=UUID(int=200 + index),
        text=f"  합성 원문 {index}\n공백과 부정문을 바꾸지 않는다.  ", ordinal=index,
        char_start=index * 40, char_end=index * 40 + 38,
        bbox=(1.0000000001, 2.5, 30.5, float(40 + index)),
        page=2, section_path=("합성 상품", "지급"),
    ) for index in range(28))
    selected = request(original)
    selected = replace(selected, profile=replace(selected.profile, response_schema_version=schema))
    expected = evidence_payload(original, contextual=True)
    raw = _generation_user_content(selected)
    payload = json.loads(raw)
    assert len(payload["evidence_groups"]) == 1
    assert [item["group_ref"] for item in payload["evidence"]] == [0] * len(original)
    assert restore(payload) == expected
    assert evidence_payload(original, contextual=True) == expected
    legacy = deepcopy(expected)
    for item in legacy:
        for key in ("document_id", "asset_version_id", "projection_id", "chunk_id",
                    "context_notice"):
            item.pop(key)
    legacy_size = len(json.dumps(legacy, ensure_ascii=False, separators=(",", ":")).encode())
    assert len(raw.encode()) < legacy_size * 0.7


def test_interleaved_groups_preserve_table_cells_nulls_empty_values_and_order():
    first = replace(evidence(), page=None, section_path=(), ordinal=0)
    second = replace(first, evidence_id=UUID(int=32), chunk_id=UUID(int=72), page=3,
                     source_kind="table_cell", source_part="table:1",
                     table_cell=TableCellLocation(2, 3, 2, 1), ordinal=4)
    third = replace(first, evidence_id=UUID(int=33), page=2, section_path=("다른 절",),
                    source_part="", ordinal=1)
    fourth = replace(second, evidence_id=UUID(int=34), ordinal=5,
                     table_cell=TableCellLocation(3, 4))
    original = (first, second, third, fourth)
    payload = json.loads(_generation_user_content(request(original)))
    assert [item["group_ref"] for item in payload["evidence"]] == [0, 1, 0, 1]
    assert "page" not in payload["evidence_groups"][0]
    assert "table_cell" not in payload["evidence_groups"][1]
    assert restore(payload) == evidence_payload(original, contextual=True)


def test_empty_context_does_not_invent_evidence_groups():
    payload = json.loads(_generation_user_content(request(())))
    assert payload["evidence"] == []
    assert "evidence_groups" not in payload


def test_noncontextual_request_preserves_legacy_json_bytes():
    original = request((evidence(),))
    legacy = replace(original, profile=replace(original.profile, evidence_budget=None))
    assert _generation_user_content(legacy) == json.dumps({
        "schema_version": legacy.profile.response_schema_version,
        "question": legacy.question,
        "resolved_query": legacy.resolved_query,
        "history": [],
        "evidence": [{"evidence_id": str(evidence().evidence_id), "text": evidence().text}],
    }, ensure_ascii=False)
