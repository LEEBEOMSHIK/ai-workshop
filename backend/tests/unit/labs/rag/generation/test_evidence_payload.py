import json
from dataclasses import replace

from ai_workshop.labs.rag.documents.domain import TableCellLocation
from ai_workshop.labs.rag.generation.codex_prompt import build_codex_prompt
from ai_workshop.labs.rag.generation.evidence_payload import serialize_evidence
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from tests.unit.labs.rag.generation.test_codex_prompt import (
    make_evidence,
    make_generation_request,
    make_profile,
)


def test_context_payload_keeps_source_identity_and_exact_text():
    unit = replace(make_evidence("synthetic body"), section_path=("Section",), ordinal=2)
    row = serialize_evidence((unit,))[0]
    assert row["text"] == unit.text
    assert row["document_id"] == str(unit.document_id)
    assert row["element_id"] == str(unit.element_id)
    assert row["section_path"] == ["Section"]
    request = make_generation_request(evidence=(unit,), profile=make_profile(
        prompt_ref="rag-codex-answer-v4", evidence_budget=EvidenceBudget(8, 32, 12000)))
    envelope = build_codex_prompt(request)
    assert json.loads(envelope.stdin_json)["evidence"] == [row]
    assert envelope.task_version == 4
    assert envelope.schema_ref == "codex-grounded-wire-v1"


def test_context_payload_preserves_table_and_visual_location():
    unit = replace(make_evidence("synthetic cell"), table_cell=TableCellLocation(2, 3, 1, 2),
                   source_kind="docx_image", source_part="word/media/image1.png",
                   bbox=(0.1, 0.2, 0.3, 0.4))
    row = serialize_evidence((unit,))[0]
    assert row["table_cell"] == {"row": 2, "column": 3, "row_span": 1, "column_span": 2}
    assert row["source_part"] == unit.source_part
    assert row["source_kind"] == "docx_image"
    assert row["bbox"] == [0.1, 0.2, 0.3, 0.4]
