from ai_workshop.labs.rag.domains.schemas import DomainSearchRequest
from ai_workshop.labs.rag.search.schemas import SearchRequest, SearchResponse


def test_diagnostics_are_explicit_and_additive():
    assert SearchRequest.model_fields["include_diagnostics"].default is False
    assert DomainSearchRequest.model_fields["include_diagnostics"].default is False
    assert "diagnostics" in SearchResponse.model_fields
    assert "grounding_evidence" in SearchResponse.model_fields
