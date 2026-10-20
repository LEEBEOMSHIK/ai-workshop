import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.generation.local_model_host import (
    LocalModelHost,
    LocalModelOutput,
    LocalModelSpec,
)
from ai_workshop.labs.rag.generation.runtime_resolver import GenerationRuntimeResolver
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import SparseHit
from ai_workshop.labs.rag.search.schemas import SearchRequest, SearchResponse
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.highlighting.test_context import ContextEmbedding
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    INSTALLATION_POLICY_ID,
    WORKSPACE_ID,
    _configuration,
    _service,
)
from tests.unit.labs.rag.search.test_provider_insufficient_evidence import ActiveScopeResolver


@pytest.mark.parametrize("wrong_citation", [False, True])
async def test_local_runtime_reaches_existing_citation_gate_without_codex(
    tmp_path: Path,
    wrong_citation: bool,
) -> None:
    source = _source(1, "The warranty lasts two years.")
    calls = []

    class Engine:
        def generate(self, **kwargs):
            payload = json.loads(kwargs["user_content"])
            calls.append(payload)
            citation = str(uuid4()) if wrong_citation else payload["evidence"][0]["evidence_id"]
            return LocalModelOutput(
                json.dumps(
                    {
                        "schema_version": 2,
                        "status": "answered",
                        "claims": [
                            {
                                "text": "The warranty lasts two years.",
                                "evidence_ids": [citation],
                            }
                        ],
                    }
                ),
                100,
                30,
            )

    class Retriever:
        async def search_sparse(self, **kwargs):
            return (SparseHit(source.chunk, 1, 7.2),)

    class Sources:
        async def resolve(self, **kwargs):
            return (source,)

    class ForbiddenCodex:
        def create(self, **kwargs):
            pytest.fail("Local inference must never construct a Codex runtime")

    config = _configuration(approval=None)
    original = config.generation_profile
    deployment = replace(
        original.deployment,
        provider=ProviderKind.LOCAL_TRANSFORMERS,
        location=ExecutionLocation.LOCAL,
        endpoint_ref=None,
        secret_ref=None,
        external_transfer=False,
        transmitted_data_categories=(),
        data_processing_notice_ref=None,
        max_retries=0,
        retry_backoff_seconds=0,
        local_model_ref="local-test",
    )
    config = replace(
        config,
        embedding=ContextEmbedding(),
        generation_profile=replace(
            original,
            deployment=deployment,
            response_schema_version=2,
            prompt_ref="rag-answer-v2",
            evidence_budget=EvidenceBudget(8, 32, 12000),
        ),
    )
    service, _, _, audits = _service(
        configuration=config,
        decision=PolicyDecision(
            True,
            None,
            INSTALLATION_POLICY_ID,
            (),
        ),
    )
    host = LocalModelHost(loader=lambda _: Engine())
    service.generation_runtime_resolver = GenerationRuntimeResolver(
        environment="test",
        endpoint_refs={},
        secret_refs={},
        factories={},
        local_model_host=host,
        local_model_refs={
            "local-test": LocalModelSpec(
                model_id=deployment.provider_model_id,
                revision="a" * 40,
                snapshot_path=tmp_path,
                max_input_tokens=2048,
            )
        },
    )
    service.codex_runtime_factory = ForbiddenCodex()
    service.sparse_retriever = Retriever()
    service.source_resolver = Sources()
    service.scope_resolver = ActiveScopeResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    request = SearchRequest(
        query="warranty",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        experimental=True,
    )
    try:
        if wrong_citation:
            with pytest.raises(AppError, match="citation"):
                await service.search(actor_id=ACTOR_ID, request=request)
        else:
            response = SearchResponse.from_domain(
                await service.search(
                    actor_id=ACTOR_ID,
                    request=request,
                )
            )
            assert response.generation.status == "answered"
            assert response.generation.citations[0].claim_text == "The warranty lasts two years."
            assert audits.audits[-1].input_tokens == 100
        assert calls
    finally:
        await host.aclose()
