from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationStatus,
    StructuredGeneration,
    generation_execution_snapshot,
)
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.generation.numeric_proof_serialization import numeric_payload_digest
from ai_workshop.labs.rag.generation.numeric_proof_types import (
    CalculationProposal,
    NumericValidationBinding,
)
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.search.pipeline import PreparedGeneration
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.generation.numeric_proof_fixtures import numeric_fixture
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    INSTALLATION_POLICY_ID,
    _approval,
    _configuration,
    _service,
)
from tests.unit.labs.rag.search.test_provider_insufficient_evidence import InsufficientRuntime


def test_legacy_validator_cannot_accept_schema3_or_calculation_proposals():
    fixture = numeric_fixture(("0.30%",))
    value = GeneratedClaim("0.30%", (fixture.evidence[0].evidence_id,))
    for draft in (
        StructuredGeneration(3, (value,)),
        StructuredGeneration(
            2, (replace(value, calculations=(CalculationProposal("convert_krw_unit", (), 0, 5),)),)
        ),
    ):
        result = CitationValidator().validate(draft, allowed_evidence=fixture.evidence)
        assert result.status is GenerationStatus.CITATION_VALIDATION_FAILED
        assert result.text is None and result.citations == ()


@pytest.mark.parametrize("mode", ["answer", "insufficient", "empty", "bad", "limit", "commit-fail"])
async def test_pipeline_numeric_proof_is_committed_before_return_and_never_bypassed(mode):
    fixture = numeric_fixture(("0.30%", "0.20%"))
    configuration = _configuration(approval=_approval())
    deployment = replace(
        configuration.generation_profile.deployment,
        provider=ProviderKind.DEVELOPMENT_CODEX_EXEC,
        runner_ref="synthetic-codex",
        endpoint_ref=None,
        secret_ref=None,
        development_only=True,
        healthcheck_enabled=False,
    )
    profile = replace(
        configuration.generation_profile,
        deployment=deployment,
        response_schema_version=3,
        prompt_ref="rag-codex-answer-v6",
        numeric_proof_policy=fixture.profile.numeric_proof_policy,
    )
    configuration = replace(configuration, generation_profile=profile)
    decision = PolicyDecision(True, None, INSTALLATION_POLICY_ID, (), workspace_policy_snapshots=())
    service, _, _, audits = _service(configuration=configuration, decision=decision)
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    request_id = UUID(int=97)

    class Runtime(InsufficientRuntime):
        received = None

        async def generate(self, request):
            self.received = request
            if mode == "insufficient":
                return ProviderGenerationResult(
                    None, self.execution, status=GenerationStatus.INSUFFICIENT_EVIDENCE
                )
            assert request.numeric_catalogue.request_id == request_id
            tokens = tuple(token.token_id for token in request.numeric_catalogue.tokens)
            value = "0.11%p" if mode == "bad" else "0.10%p"
            return ProviderGenerationResult(
                StructuredGeneration(
                    3,
                    (
                        GeneratedClaim(
                            value,
                            tuple(e.evidence_id for e in request.evidence),
                            (
                                CalculationProposal(
                                    "percentage_point_difference", tokens, 0, len(value)
                                ),
                            ),
                        ),
                    ),
                ),
                self.execution,
            )

    runtime = Runtime(None)
    runtime.execution = replace(runtime.execution, provider=deployment.provider)
    saved = []

    async def add_validated(audit, validated):
        assert audits.commits == 0
        assert validated.payload is not None
        saved.append(validated)
        audits.audits.append(audit)
        payload = validated.payload
        return NumericValidationBinding(
            uuid4(),
            audit.id,
            payload.request_id,
            payload.configuration_version_id,
            payload.generation_profile_id,
            3,
            payload.policy_ref,
            payload.policy_digest,
            payload.catalogue_digest,
            numeric_payload_digest(payload),
        )

    async def fail_commit():
        raise RuntimeError("synthetic failure")

    audits.add_validated = add_validated
    if mode == "commit-fail":
        audits.commit = fail_commit
    arguments = dict(
        actor_id=ACTOR_ID,
        original_query="difference",
        resolved_query="difference",
        history=(),
        configuration=configuration,
        selection=None,
        evidence=()
        if mode == "empty"
        else (replace(fixture.evidence[0], text="1" * 31 + "원", char_end=100),)
        if mode == "limit"
        else fixture.evidence,
        prepared_generation=PreparedGeneration(
            runtime, decision, generation_execution_snapshot(profile), request_id
        ),
        contextualization_execution=None,
        conversation_scope=None,
    )
    if mode in {"bad", "limit", "commit-fail"}:
        with pytest.raises(AppError):
            await service._generate(**arguments)
        if mode != "commit-fail":
            assert saved == []
        if mode == "limit":
            assert runtime.received is None
        return
    outcome = await service._generate(**arguments)
    assert audits.commits == 1 and len(saved) == 1
    assert outcome.numeric_validation.payload_digest == numeric_payload_digest(saved[0].payload)
    assert outcome.numeric_validation.request_id == request_id
    if mode == "answer":
        assert outcome.text == "0.10%p" and outcome.citations[0].calculations
    else:
        assert outcome.status is GenerationStatus.INSUFFICIENT_EVIDENCE
        assert outcome.text is None and outcome.citations == ()
