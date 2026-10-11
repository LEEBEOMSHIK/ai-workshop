import json

import pytest

from ai_workshop.labs.rag.generation.structured_output import StructuredOutputValidationError
from ai_workshop.labs.rag.models.numeric_proof_policy import SOURCE_NUMERIC_PROOF_V1

from .numeric_proof_fixtures import numeric_fixture


def draft_json(fixture, *, text="😀 difference 0.10%p"):
    return {
        "schema_version": 3,
        "status": "answered",
        "claims": [
            {
                "text": text,
                "evidence_ids": [str(item.evidence_id) for item in fixture.evidence],
                "calculations": [
                    {
                        "operation": "percentage_point_difference",
                        "operand_token_ids": [t.token_id for t in fixture.catalogue.tokens],
                        "result_start": text.index("0.10"),
                        "result_end": len(text),
                    }
                ],
            }
        ],
    }


def parse(value, fixture):
    from ai_workshop.labs.rag.generation.structured_output_v3 import parse_grounded_generation_v3

    return parse_grounded_generation_v3(
        json.dumps(value),
        allowed_evidence_ids={e.evidence_id for e in fixture.evidence},
        policy=SOURCE_NUMERIC_PROOF_V1,
    )


def test_closed_schema3_roundtrip_preserves_codepoints():
    fixture = numeric_fixture(("0.30%", "0.20%"))
    parsed = parse(draft_json(fixture), fixture)
    assert parsed.generation is not None
    claim = parsed.generation.claims[0]
    assert claim.text == "😀 difference 0.10%p"
    assert claim.calculations[0].result_start == 13
    assert claim.calculations[0].result_end == 19


@pytest.mark.parametrize(
    "mutation",
    [
        "boolean",
        "float",
        "unknown-key",
        "unknown-operation",
        "whitespace",
        "nul",
        "surrogate",
        "too-many-proofs",
    ],
)
def test_boolean_span_unicode_and_unknown_fields(mutation):
    fixture = numeric_fixture(("0.30%", "0.20%"))
    data = draft_json(fixture)
    claim = data["claims"][0]
    proof = claim["calculations"][0]
    if mutation == "boolean":
        proof["result_start"] = True
    elif mutation == "float":
        proof["result_start"] = 1.0
    elif mutation == "unknown-key":
        proof["result_value"] = 0.1
    elif mutation == "unknown-operation":
        proof["operation"] = "eval"
    elif mutation == "whitespace":
        claim["text"] = " " + claim["text"]
    elif mutation == "nul":
        claim["text"] += "\0"
    elif mutation == "surrogate":
        claim["text"] += "\ud800"
    else:
        claim["calculations"] *= 33
    with pytest.raises(StructuredOutputValidationError):
        parse(data, fixture)


def test_duplicate_keys_and_insufficient_closed_shape():
    from ai_workshop.labs.rag.generation.structured_output_v3 import parse_grounded_generation_v3

    for value in [
        '{"schema_version":3,"schema_version":3,"status":"insufficient_evidence"}',
        '{"schema_version":3,"status":"insufficient_evidence","claims":[]}',
    ]:
        with pytest.raises(StructuredOutputValidationError):
            parse_grounded_generation_v3(
                value, allowed_evidence_ids=(), policy=SOURCE_NUMERIC_PROOF_V1
            )
    result = parse_grounded_generation_v3(
        '{"schema_version":3,"status":"insufficient_evidence"}',
        allowed_evidence_ids=(),
        policy=SOURCE_NUMERIC_PROOF_V1,
    )
    assert result.generation is None
