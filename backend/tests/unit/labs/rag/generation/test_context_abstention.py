import pytest

from ai_workshop.labs.rag.generation.evidence_payload import is_context_abstention


@pytest.mark.parametrize("content,expected", [
    ('{"schema_version":1,"claims":[]}', True),
    ('{"schema_version":true,"claims":[]}', False),
    ('{"schema_version":2,"claims":[]}', False),
    ('{"schema_version":2,"schema_version":1,"claims":[]}', False),
    ('{"schema_version":1,"claims":[],"extra":"hidden"}', False),
    ('not json', False),
])
def test_only_exact_context_abstention_is_accepted(content, expected):
    assert is_context_abstention(content) is expected
