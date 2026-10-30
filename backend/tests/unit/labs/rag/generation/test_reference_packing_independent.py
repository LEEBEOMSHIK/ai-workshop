"""Independent lossless encoding and pre-change v5 byte contracts; no model quality claim."""
import hashlib
import json
from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.compact_evidence import pack_compact_evidence
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.openai_compatible import (
    http_answer_instructions,
    http_answer_schema,
    http_generation_input,
    parse_http_answer,
)
from tests.unit.labs.rag.generation.test_source_reading import (
    request_for,
    source_units,
    stored_evidence,
)


def test_preimplementation_v5_bytes_and_instructions_remain_exact():
    request = request_for(stored_evidence(), reference="rag-answer-v5")
    values = {
        "input": http_generation_input(request),
        "ollama": http_answer_instructions(request.profile, dialect="ollama"),
        "openai": http_answer_instructions(request.profile, dialect="openai"),
        "schema": json.dumps(http_answer_schema(), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")),
    }
    expected = {
        "input": "5839051b4e1148819ed66fe338b58554e53ec424e031d7ca17d19cd71f5487ae",
        "ollama": "550dcf8b8bf3ee240bcc58358a34d0ed5071cb038132a5887ccf7751fb49415f",
        "openai": "3c0e30b069c580b24b90a6dc61459422bf6033e83a37c7a81a7b67b0455e72e8",
        "schema": "935d50561871d813fd18c9601d089ae5582e297d92c9796e8fda991620ff6895",
    }
    assert {key: hashlib.sha256(value.encode()).hexdigest() for key, value in values.items()} == (
        expected
    )


@pytest.mark.parametrize("case", ["stored", "empty", "unicode", "reversed", "same_text"])
def test_v6_rows_independently_reconstruct_every_v5_fragment_and_source(case):
    from ai_workshop.labs.rag.generation.reference_evidence import pack_reference_evidence

    items = stored_evidence()
    if case == "empty":
        items = ()
    elif case == "unicode":
        items = source_units([" e1\n가\t😀 ", "e01 e2 1.000  UUID remains"])
        items = (replace(items[0], bbox=(0.125, 1.5, 20.25, 33.75)), items[1])
    elif case == "reversed":
        items = tuple(reversed(items))
    elif case == "same_text":
        items = source_units(["same", "same"])
        items = (items[0], replace(items[1], document_id=UUID(int=700)))
    original = pack_compact_evidence(items)
    packed = pack_reference_evidence(items)
    payload = packed.payload
    assert payload["fragment_columns"] == ["evidence_ref", "text", "bbox", "char_range", "ordinal"]
    assert payload["evidence_sources"] == original["evidence_sources"]
    assert packed.reference_ids == tuple(item.evidence_id for item in items)
    assert list(packed.reference_map) == [f"e{i}" for i in range(1, len(items) + 1)]
    decoded = []
    seen = []
    for block in payload["evidence_blocks"]:
        fragments = []
        for row in block["rows"]:
            alias, content, bbox, char_range, ordinal = row
            seen.append(alias)
            fragments.append({"evidence_id": str(items[int(alias[1:]) - 1].evidence_id),
                              "text": content, "bbox": bbox, "char_range": char_range,
                              "ordinal": ordinal})
        decoded.append({"source_ref": block["source_ref"], "fragments": fragments})
    assert decoded == original["evidence_blocks"]
    assert seen == [f"e{i}" for i in range(1, len(items) + 1)]
    with pytest.raises(TypeError):
        packed.reference_map["e1"] = UUID(int=999)


@pytest.mark.parametrize("refs", [["e0"], ["e3"], ["e01"], ["E1"], [" e1"],
                                  ["e1", "e1"], [str(UUID(int=100))],
                                  ["e1", str(UUID(int=101))]])
def test_v6_rejects_unknown_noncanonical_duplicate_and_raw_uuid_citations(refs):
    selected = request_for(source_units(["a", "b"]), reference="rag-answer-v6")
    content = json.dumps({"schema_version": 2, "status": "answered",
                          "claims": [{"text": "literal e1 unchanged", "evidence_ids": refs}]})
    with pytest.raises(GenerationProviderError):
        parse_http_answer(content, request=selected)


def test_v6_restores_only_citation_ids_and_preserves_claim_text():
    items = source_units(["a", "b"])
    selected = request_for(items, reference="rag-answer-v6")
    content = json.dumps({"schema_version": 2, "status": "answered", "claims": [{
        "text": "literal e1 and " + str(items[0].evidence_id), "evidence_ids": ["e2", "e1"],
    }]})
    answer = parse_http_answer(content, request=selected)
    assert answer.claims[0].evidence_ids == (items[1].evidence_id, items[0].evidence_id)
    assert answer.claims[0].text == "literal e1 and " + str(items[0].evidence_id)
    abstain = parse_http_answer(
        '{"schema_version":2,"status":"insufficient_evidence","claims":[]}', request=selected,
    )
    assert abstain.claims == ()


def test_legacy_parser_does_not_accept_alias_without_v6_request():
    with pytest.raises(GenerationProviderError):
        parse_http_answer('{"schema_version":2,"status":"answered",'
                          '"claims":[{"text":"a","evidence_ids":["e1"]}]}')
