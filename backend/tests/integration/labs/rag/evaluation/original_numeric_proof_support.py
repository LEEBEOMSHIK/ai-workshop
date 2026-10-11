"""One existing connection, COMMIT denied, exact protected inventory restored.

The owner judgments below are temporary SQL contract fixtures. They are not
model answers or real correctness reviews and cannot survive outer rollback.
"""

# ruff: noqa: E501
import json
import os
import re
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

import ai_workshop.main  # noqa: F401
from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationVersionRecord,
)
from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.documents.models import EvidenceUnitRecord
from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.generative_models import (
    GenerativeAttemptRecord,
    GenerativeRunRecord,
)
from ai_workshop.labs.rag.evaluation.generative_repository import canonical
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.generation.audit import (
    GenerationExecutionAudit,
    SqlAlchemyGenerationAuditRepository,
)
from ai_workshop.labs.rag.generation.audit_models import GenerationExecutionAuditRecord
from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GroundingEvidence,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.numeric_catalogue import build_source_value_catalogue
from ai_workshop.labs.rag.generation.numeric_proof_schemas import (
    NumericValidationBindingView,
    calculation_views,
    payload_from_views,
)
from ai_workshop.labs.rag.generation.numeric_proof_serialization import (
    canonical_numeric_payload,
    numeric_payload_digest,
)
from ai_workshop.labs.rag.generation.numeric_proof_types import CalculationProposal
from ai_workshop.labs.rag.generation.numeric_validation import (
    NumericProofValidator,
    validated_numeric_abstention,
)
from ai_workshop.labs.rag.generation.numeric_validation_models import NumericValidationRecord
from ai_workshop.labs.rag.generation.numeric_validation_repository import (
    SqlAlchemyNumericValidationRepository,
    binding_from_record,
)
from ai_workshop.labs.rag.generation.numeric_validation_sql import NUMERIC_PROOF_DDL
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.indexing.alias_recovery_cli import load_original_settings
from ai_workshop.labs.rag.models.models import ProfileDeploymentBindingRecord, ProfileRecord
from ai_workshop.shared.db import create_engine
from ai_workshop.shared.errors import AppError


class OriginalNumericProofTrialError(RuntimeError):
    """Only fixed phase identifiers; never driver/SQL/body representations."""


def require(value, code):
    if not value:
        raise OriginalNumericProofTrialError(code)


def clone(record, **changes):
    values = {
        column.name: deepcopy(getattr(record, column.name)) for column in record.__table__.columns
    }
    values.update(changes)
    return type(record)(**values)


PROTECTED_TABLES = (
    "users",
    "documents",
    "asset_versions",
    "rag_profiles",
    "rag_configuration_versions",
    "rag_generative_runs",
    "rag_generative_attempts",
    "rag_generative_judgments",
    "rag_generative_acceptances",
    "rag_generation_execution_audits",
    "rag_alias_operations",
    "rag_alias_cluster_gates",
    "rag_alias_recovery_receipts",
)


async def inventory(connection):
    result = {
        "schema": await connection.scalar(text("SELECT version_num FROM alembic_version")),
        "gate": (
            await connection.execute(
                text(
                    "SELECT oid::text,encode(sha256(convert_to(pg_get_functiondef(oid),'UTF8')),'hex') FROM pg_proc WHERE oid='rag_verify_generative_candidate(uuid,uuid)'::regprocedure"
                )
            )
        ).one(),
    }
    for name in PROTECTED_TABLES:
        result[name] = (
            await connection.execute(
                text(
                    f"SELECT count(*),encode(sha256(convert_to(coalesce(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]')::text,'UTF8')),'hex') FROM {name} t"
                )
            )
        ).one()
    return result


class NumericTrial:
    def __init__(self, connection, sessions):
        self.connection, self.sessions = connection, sessions
        self.phase = "numeric_trial_fixture_failed"
        self.examples = []

    async def seed(self):
        async with self.sessions() as session:
            template = await session.get(
                GenerativeRunRecord, UUID("b5cd916f-01fa-43c1-8cd2-37a5655c2394")
            )
            require(template is not None, "numeric_trial_snapshot_required")
            actor = await session.scalar(
                text("SELECT id FROM users WHERE role='owner' AND is_active LIMIT 1")
            )
            require(actor == template.owner_id, "numeric_trial_owner_required")
            self.actor = actor
            original_candidate = template.snapshot["candidates"][0]
            old = await session.get(
                RagConfigurationVersionRecord, UUID(original_candidate["configuration_version_id"])
            )
            self.legacy_config_id = old.id
            original_profile = await session.get(ProfileRecord, old.generation_profile_id)
            deployment_binding = await session.get(
                ProfileDeploymentBindingRecord, original_profile.id
            )
            original_audit = await session.scalar(
                select(GenerationExecutionAuditRecord)
                .where(
                    GenerationExecutionAuditRecord.configuration_version_id == old.id,
                    GenerationExecutionAuditRecord.actor_id == actor,
                    GenerationExecutionAuditRecord.policy_allowed.is_(True),
                )
                .limit(1)
            )
            require(
                deployment_binding is not None and original_audit is not None,
                "numeric_trial_deployment_required",
            )
            self.original_profile_id = original_profile.id
            generation_config = deepcopy(original_profile.config)
            generation_config["prompt_ref"] = "rag-codex-answer-v6"
            generation_config["generation"].update(
                response_schema_version=3, numeric_proof_policy_ref="source-numeric-proof-v1"
            )
            generation_config["context_evidence"] = {
                "version": 1,
                "max_groups": 8,
                "max_units": 32,
                "max_characters": 12000,
            }
            profile = clone(
                original_profile,
                id=uuid4(),
                name="numeric-sql-trial-" + str(uuid4()),
                config=generation_config,
                is_default=False,
                evaluation_state="pending",
            )
            session.add(profile)
            await session.flush()
            session.add(
                ProfileDeploymentBindingRecord(
                    profile_id=profile.id,
                    deployment_version_id=deployment_binding.deployment_version_id,
                )
            )
            next_version = 1 + await session.scalar(
                select(func.max(RagConfigurationVersionRecord.version)).where(
                    RagConfigurationVersionRecord.configuration_id == old.configuration_id
                )
            )
            answer_policy = clone(
                await session.get(AnswerPolicyVersionRecord, old.answer_policy_version_id),
                id=uuid4(),
                version=next_version,
            )
            session.add(answer_policy)
            await session.flush()
            configuration = clone(
                old,
                id=uuid4(),
                version=next_version,
                generation_profile_id=profile.id,
                answer_policy_version_id=answer_policy.id,
                is_default=False,
                evaluation_state="pending",
            )
            session.add(configuration)
            await session.flush()
            repository = SqlAlchemyRagConfigurationRepository(session)
            await session.refresh(profile, ["bindings"])
            selected_profile = await repository.find_profile(profile.id)
            deployment = await repository.get_deployment_version(
                deployment_binding.deployment_version_id
            )
            model = await repository.get_model_definition(deployment.model_definition_id)
            self.profile = resolve_generation_profile(selected_profile, deployment, model)
            require(
                deployment.provider is ProviderKind.DEVELOPMENT_CODEX_EXEC,
                "numeric_trial_codex_required",
            )
            self.config_id = configuration.id
            snapshot = deepcopy(template.snapshot)
            candidate = deepcopy(original_candidate)
            candidate["configuration_version_id"] = str(configuration.id)
            component = candidate["component_snapshot"]
            component["configuration"]["version_id"] = str(configuration.id)
            component["configuration"]["version"] = configuration.version
            component["answer_policy"]["id"] = str(answer_policy.id)
            for item in component["profiles"]:
                if item["id"] == str(original_profile.id):
                    item.update(
                        id=str(profile.id),
                        name=profile.name,
                        version=profile.version,
                        config=generation_config,
                    )
            snapshot["candidates"] = [candidate]
            raw = canonical(snapshot)
            self.run = clone(
                template,
                id=uuid4(),
                request_id=uuid4(),
                snapshot=snapshot,
                snapshot_bytes=raw,
                snapshot_digest=sha256(raw).hexdigest(),
                status="running",
                claim_token=uuid4(),
                claimed_at=datetime.now(UTC),
                finished_at=None,
                runtime_environment={"fixture": "transaction-only numeric SQL contract"},
            )
            session.add(self.run)
            await session.flush()
            frozen = {}
            for source in snapshot["sources"]:
                permitted = await session.scalar(
                    text("""SELECT av.id FROM asset_versions av
                    JOIN documents d ON d.id=av.document_id JOIN workspaces w ON w.id=d.workspace_id
                    JOIN workspace_memberships m ON m.workspace_id=w.id AND m.user_id=:actor
                    JOIN users u ON u.id=m.user_id JOIN rag_evidence_approval_states a ON a.revision_id=av.id
                    WHERE av.id=:version AND av.sha256=:digest AND av.status='ready' AND d.lifecycle='active'
                      AND u.is_active AND (w.kind<>'personal' OR w.created_by=:actor)
                      AND (w.kind<>'company' OR m.role='owner' OR m.can_read)
                      AND (w.kind<>'temporary' OR w.expires_at>now())
                      AND a.provider='development_codex_exec' AND a.status='approved'
                      AND a.revoked_at IS NULL AND a.classification='synthetic' AND a.content_sha256=av.sha256"""),
                    {
                        "actor": actor,
                        "version": UUID(source["asset_version_id"]),
                        "digest": source["asset_sha256"],
                    },
                )
                require(permitted is not None, "numeric_trial_source_approval_required")
                for unit in source["evidence_units"]:
                    actual = await session.get(EvidenceUnitRecord, UUID(unit["id"]))
                    require(
                        actual is not None
                        and actual.text == unit["text"]
                        and actual.projection_id == UUID(source["projection_id"]),
                        "numeric_trial_source_hash_required",
                    )
                    frozen[actual.id] = GroundingEvidence(
                        actual.id,
                        actual.text,
                        UUID(source["document_id"]),
                        UUID(source["asset_version_id"]),
                        actual.projection_id,
                        actual.retrieval_chunk_id,
                        actual.element_id,
                        actual.page,
                        actual.char_start,
                        actual.char_end,
                        tuple(actual.bbox) if actual.bbox else None,
                    )
            for case_id, rule in self.run.expected_rules.items():
                selected = (
                    tuple(
                        dict.fromkeys(UUID(group[0]) for group in rule["required_evidence_groups"])
                    )
                    if rule["expected_answer_status"] == "answered"
                    else ()
                )
                evidence = tuple(frozen[identity] for identity in selected)
                for repetition in range(self.run.repetition_count):
                    attempt = GenerativeAttemptRecord(
                        id=uuid4(),
                        run_id=self.run.id,
                        configuration_version_id=self.config_id,
                        case_id=UUID(case_id),
                        repetition=repetition,
                        attempt_number=1,
                        execution_id=uuid4(),
                        status="running",
                        claim_token=self.run.claim_token,
                    )
                    session.add(attempt)
                    await session.flush()
                    session.add(
                        ExecutionRecord(
                            id=attempt.execution_id,
                            actor_id=actor,
                            evaluation_attempt_id=attempt.id,
                            status="completed",
                            complete=True,
                            ended_at=datetime.now(UTC),
                        )
                    )
                    await session.flush()
                    catalogue = build_source_value_catalogue(
                        evidence,
                        request_id=uuid4(),
                        configuration_version_id=self.config_id,
                        profile=self.profile,
                    )
                    if not evidence:
                        validated = validated_numeric_abstention(
                            catalogue=catalogue,
                            profile=self.profile,
                            request_id=catalogue.request_id,
                            configuration_version_id=self.config_id,
                        )
                    else:
                        claims = []
                        for item in evidence:
                            value, calculations = item.text.strip(), ()
                            token = next(
                                (
                                    token
                                    for token in catalogue.tokens
                                    if token.evidence_id == item.evidence_id
                                    and token.unit in ("원", "만원", "억원")
                                ),
                                None,
                            )
                            if token is not None:
                                target = "원" if token.unit != "원" else "만원"
                                scales = {
                                    "원": Decimal(1),
                                    "만원": Decimal(10000),
                                    "억원": Decimal(100000000),
                                }
                                with localcontext() as context:
                                    context.prec = 64
                                    result = (
                                        format(
                                            token.value * scales[token.unit] / scales[target], "f"
                                        )
                                        + target
                                    )
                                prefix = value + " 단위 환산 "
                                value = prefix + result
                                calculations = (
                                    CalculationProposal(
                                        "convert_krw_unit",
                                        (token.token_id,),
                                        len(prefix),
                                        len(value),
                                    ),
                                )
                            claims.append(GeneratedClaim(value, (item.evidence_id,), calculations))
                        percentages = [token for token in catalogue.tokens if token.unit == "%"]
                        if (
                            not any(claim.calculations for claim in claims)
                            and len(percentages) >= 2
                        ):
                            left, right = percentages[:2]
                            with localcontext() as context:
                                context.prec = 64
                                difference = format(left.value - right.value, "f") + "%p"
                            prefix = "합성 SQL 계약 계산 검증 "
                            claims.append(
                                GeneratedClaim(
                                    prefix + difference,
                                    tuple(dict.fromkeys((left.evidence_id, right.evidence_id))),
                                    (
                                        CalculationProposal(
                                            "percentage_point_difference",
                                            (left.token_id, right.token_id),
                                            len(prefix),
                                            len(prefix + difference),
                                        ),
                                    ),
                                )
                            )
                        validated = NumericProofValidator().validate(
                            StructuredGeneration(3, tuple(claims)),
                            evidence=evidence,
                            catalogue=catalogue,
                            profile=self.profile,
                            request_id=catalogue.request_id,
                            configuration_version_id=self.config_id,
                        )
                    require(validated.payload is not None, "numeric_trial_validation_failed")
                    audit = GenerationExecutionAudit(
                        uuid4(),
                        actor,
                        self.config_id,
                        self.profile.profile_id,
                        deployment.id,
                        original_audit.installation_policy_version_id,
                        (),
                        ProviderKind.DEVELOPMENT_CODEX_EXEC,
                        deployment.provider_model_id,
                        ExecutionLocation.EXTERNAL,
                        True,
                        True,
                        None,
                        "rag-codex-answer-v6",
                        6,
                        selected,
                        None,
                        None,
                        1,
                        None,
                        None,
                        None,
                        None,
                        "succeeded" if evidence else "allowed",
                        None,
                        uuid4(),
                        datetime.now(UTC),
                        attempt.execution_id,
                    )
                    binding = await SqlAlchemyGenerationAuditRepository(session).add_validated(
                        audit, validated
                    )
                    result = PrivateGenerativeResult(
                        observation=GenerativeObservation(
                            execution_id=attempt.execution_id,
                            retrieved_evidence_ids=selected,
                            selected_evidence_ids=selected,
                            cited_evidence_ids=selected,
                            generation_status=validated.outcome.status.value,
                            citation_valid=True if evidence else None,
                            duration_ms=1,
                        ),
                        answer=validated.outcome.text,
                        citations=tuple(
                            ClaimCitation(
                                claim_index=c.claim_index,
                                claim_text=c.claim_text,
                                evidence_ids=c.evidence_ids,
                                calculations=calculation_views(c.calculations),
                            )
                            for c in validated.outcome.citations
                        ),
                        numeric_validation=NumericValidationBindingView.from_domain(binding),
                    )
                    attempt.result = result.model_dump(mode="json")
                    attempt.result_bytes = canonical(attempt.result)
                    attempt.result_digest = result.digest()
                    attempt.finished_at = datetime.now(UTC)
                    attempt.status = "completed"
                    await session.flush()
                    # Initial immutable terminal rows are trial fixtures, not provider executions.
                    await session.execute(
                        text(
                            "INSERT INTO rag_generative_judgments (id,attempt_id,reviewer_id,result_digest,rule_digest,status,reason,created_at,updated_at) VALUES (:id,:attempt,:actor,:result,:rule,'passed','transaction-only SQL fixture',now(),now())"
                        ),
                        {
                            "id": uuid4(),
                            "attempt": attempt.id,
                            "actor": actor,
                            "result": result.digest(),
                            "rule": sha256(canonical(rule)).hexdigest(),
                        },
                    )
                    self.examples.append((attempt, result, audit, binding))
            self.run.status = "completed"
            self.run.claim_token = None
            self.run.finished_at = datetime.now(UTC)
            await session.flush()
            await session.commit()

    async def check_gate(self):
        require(
            await self.connection.scalar(
                text("SELECT rag_verify_generative_candidate(:run,:version)"),
                {"run": self.run.id, "version": self.config_id},
            )
            is not None,
            "numeric_trial_gate_failed",
        )

    async def check_roundtrip(self):
        async with self.sessions() as session:
            example = next(
                (
                    value
                    for value in self.examples
                    if any(c.calculations for c in value[1].citations)
                ),
                None,
            )
            require(example is not None, "numeric_trial_explicit_numeric_units_required")
            attempt, result, _, binding = example
            repository = SqlAlchemyNumericValidationRepository(session)
            expected = await repository.expected_context_for_execution(
                actor_id=self.actor, execution_id=attempt.execution_id
            )
            payload = payload_from_views(
                status=result.observation.generation_status,
                answer=result.answer,
                claims=result.citations,
                binding=result.numeric_validation,
            )
            await repository.verify_binding(binding, payload, expected=expected)
            try:
                await repository.expected_context_for_execution(
                    actor_id=uuid4(), execution_id=attempt.execution_id
                )
            except AppError as exc:
                require(
                    exc.code == "numeric_validation_binding_invalid",
                    "numeric_trial_actor_rejection_invalid",
                )
            else:
                raise OriginalNumericProofTrialError("numeric_trial_wrong_actor_accepted")
            sql = await session.scalar(
                text("SELECT convert_to(rag_generative_canonical(CAST(:payload AS jsonb)),'UTF8')"),
                {"payload": canonical_numeric_payload(payload).decode()},
            )
            require(
                bytes(sql) == canonical_numeric_payload(payload), "numeric_trial_canonical_mismatch"
            )
            sample = {"text": '😀 한글\n"인용"', "span": [5, 11], "unit": "억원"}
            encoded = canonical(sample)
            sql = await session.scalar(
                text("SELECT convert_to(rag_generative_canonical(CAST(:payload AS jsonb)),'UTF8')"),
                {"payload": encoded.decode()},
            )
            require(bytes(sql) == encoded, "numeric_trial_unicode_canonical_mismatch")

    async def check_insufficient(self):
        for _attempt, result, _, binding in self.examples:
            if result.observation.generation_status == "insufficient_evidence":
                require(
                    result.answer is None and not result.citations and binding.schema_version == 3,
                    "numeric_trial_abstention_invalid",
                )
        await self.check_gate()

    async def check_legacy(self):
        await self.connection.execute(
            text("SELECT rag_require_generative_numeric_candidate(:run,:version)"),
            {"run": UUID("b5cd916f-01fa-43c1-8cd2-37a5655c2394"), "version": self.legacy_config_id},
        )

    async def reject_mutation(self, mutation):
        savepoint = await self.connection.begin_nested()
        try:
            async with self.sessions() as session:
                original, original_result, _, original_binding = next(
                    value
                    for value in self.examples
                    if any(c.calculations for c in value[1].citations)
                )
                # Terminal UPDATE defaults may be expired on the seed ORM row.
                # Reload the control in this session before copying its columns.
                original = await session.get(GenerativeAttemptRecord, original.id)
                execution_id, attempt_id, audit_id = uuid4(), uuid4(), uuid4()
                audit = clone(
                    await session.get(GenerationExecutionAuditRecord, original_binding.audit_id),
                    id=audit_id,
                    execution_id=execution_id,
                )
                receipt = clone(
                    await session.get(NumericValidationRecord, original_binding.validation_id),
                    id=uuid4(),
                    audit_id=audit_id,
                    execution_id=execution_id,
                    request_id=uuid4(),
                )
                data = original_result.model_dump(mode="json")
                data["observation"]["execution_id"] = str(execution_id)
                binding = NumericValidationBindingView.from_domain(binding_from_record(receipt))
                value = PrivateGenerativeResult.model_validate(
                    {**data, "numeric_validation": binding.model_dump(mode="json")}
                )
                receipt.payload_digest = numeric_payload_digest(
                    payload_from_views(
                        status=value.observation.generation_status,
                        answer=value.answer,
                        claims=value.citations,
                        binding=binding,
                    )
                )
                data["numeric_validation"] = NumericValidationBindingView.from_domain(
                    binding_from_record(receipt)
                ).model_dump(mode="json")
                if mutation in {"origin", "span", "self-citation"}:
                    claim = next(item for item in data["citations"] if item["calculations"])
                    if mutation == "origin":
                        claim["calculations"][0]["operands"][0]["document_id"] = str(uuid4())
                    elif mutation == "span":
                        claim["calculations"][0]["result_end"] = len(claim["claim_text"]) + 1000
                    else:
                        claim["evidence_ids"] = []
                    altered = PrivateGenerativeResult.model_validate(data)
                    receipt.payload_digest = numeric_payload_digest(
                        payload_from_views(
                            status=altered.observation.generation_status,
                            answer=altered.answer,
                            claims=altered.citations,
                            binding=altered.numeric_validation,
                        )
                    )
                    data["numeric_validation"]["payload_digest"] = receipt.payload_digest
                elif mutation == "policy":
                    receipt.policy_digest = "0" * 64
                    data["numeric_validation"]["policy_digest"] = receipt.policy_digest
                elif mutation == "profile":
                    receipt.generation_profile_id = self.original_profile_id
                    data["numeric_validation"]["generation_profile_id"] = str(
                        self.original_profile_id
                    )
                elif mutation == "request":
                    data["numeric_validation"]["request_id"] = str(uuid4())
                elif mutation == "whole-cross-execution":
                    data["numeric_validation"] = original_result.numeric_validation.model_dump(
                        mode="json"
                    )
                elif mutation == "payload":
                    data["citations"][0]["claim_text"] += " synthetic changed"
                    data["answer"] = " ".join(item["claim_text"] for item in data["citations"])
                elif mutation in {"missing-envelope", "downgrade"}:
                    data.pop("numeric_validation")
                    if mutation == "downgrade":
                        for claim in data["citations"]:
                            claim.pop("calculations")
                attempted = clone(
                    original,
                    id=attempt_id,
                    execution_id=execution_id,
                    attempt_number=2,
                    result=data,
                    result_bytes=canonical(data),
                    result_digest=sha256(canonical(data)).hexdigest(),
                )
                session.add(attempted)
                await session.flush()
                session.add(
                    ExecutionRecord(
                        id=execution_id,
                        actor_id=self.actor,
                        evaluation_attempt_id=attempt_id,
                        status="completed",
                        complete=True,
                        ended_at=datetime.now(UTC),
                    )
                )
                await session.flush()
                session.add(audit)
                await session.flush()
                if mutation != "missing-receipt":
                    session.add(receipt)
                    await session.flush()
                await session.execute(
                    text(
                        "INSERT INTO rag_generative_judgments (id,attempt_id,reviewer_id,result_digest,rule_digest,status,reason,created_at,updated_at) SELECT :id,:attempt,:actor,:digest,rule_digest,'passed','transaction-only SQL fixture',now(),now() FROM rag_generative_judgments WHERE attempt_id=:original ORDER BY created_at DESC LIMIT 1"
                    ),
                    {
                        "id": uuid4(),
                        "attempt": attempt_id,
                        "actor": self.actor,
                        "digest": attempted.result_digest,
                        "original": original.id,
                    },
                )
                await session.commit()
            expected_code = {
                "origin": "numeric_operand_origin_invalid",
                "span": "numeric_proof_invalid",
                "self-citation": "numeric_claims_invalid",
                "payload": "numeric_payload_digest_invalid",
            }.get(mutation, "numeric_validation_binding_invalid")
            rejected_code = None
            gate_succeeded = False
            check = await self.connection.begin_nested()
            try:
                await self.connection.execute(
                    text("SELECT rag_verify_generative_candidate(:run,:version)"),
                    {"run": self.run.id, "version": self.config_id},
                )
                gate_succeeded = True
            except DBAPIError as exc:
                # Compare only exact allowlisted PostgreSQL RAISE categories.
                # Never print or preserve the driver message, SQL or parameters.
                cause = exc.orig.__cause__
                message = getattr(cause, "message", None)
                if message is None:
                    message = getattr(getattr(exc.orig, "diag", None), "message_primary", None)
                if message is None:
                    first_line = str(exc.orig).splitlines()[0]
                    exact = re.fullmatch(
                        r"(?:<class 'asyncpg\.exceptions\.[A-Za-z_]+'>(?::)?\s*)?"
                        + re.escape(expected_code),
                        first_line,
                    )
                    message = expected_code if exact else None
                if message == expected_code:
                    rejected_code = expected_code
            finally:
                await check.rollback()
            if mutation == "control":
                require(gate_succeeded, "numeric_trial_control_failed")
            else:
                require(rejected_code == expected_code, "numeric_trial_expected_rejection_missing")
        finally:
            await savepoint.rollback()


@asynccontextmanager
async def original_trial(monkeypatch):
    for key in list(os.environ):
        if key.upper().startswith("AI_WORKSHOP_"):
            monkeypatch.delenv(key)
    engine = create_engine(load_original_settings(Path(__file__).resolve().parents[6]))
    engine.sync_engine.hide_parameters = True
    engine.sync_engine.echo = False

    @event.listens_for(engine.sync_engine, "commit")
    def reject_commit(connection):
        raise OriginalNumericProofTrialError("numeric_trial_outer_commit_denied")

    phase = "numeric_trial_preflight_failed"
    try:
        async with engine.connect() as connection:
            outer = await connection.begin()
            before = await inventory(connection)
            require(before["schema"] == "0061_alias_recovery", "numeric_trial_schema0061_required")
            trial_complete = False
            try:
                phase = "numeric_trial_ddl_failed"
                for statement in NUMERIC_PROOF_DDL:
                    await connection.execute(text(statement))
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                trial = NumericTrial(connection, sessions)
                phase = "numeric_trial_fixture_failed"
                await trial.seed()
                trial_complete = True
                phase = "numeric_trial_contract_failed"
                yield trial
            except Exception as exc:
                if isinstance(exc, OriginalNumericProofTrialError):
                    raise
                frame = exc.__traceback__
                line = None
                frames = []
                while frame is not None:
                    filename = Path(frame.tb_frame.f_code.co_filename).name
                    if filename in {
                        "original_numeric_proof_support.py",
                        "numeric_validation_repository.py",
                    }:
                        frames.append({"file": filename, "line": frame.tb_lineno})
                    if filename == Path(__file__).name:
                        line = frame.tb_lineno
                    frame = frame.tb_next
                category = type(exc).__name__
                if re.fullmatch(r"[A-Za-z_0-9]{1,80}", category) is None:
                    category = "unexpected"
                # Diagnostics contain only a fixed category and helper line number.
                # No exception message, SQL, parameter or source text is retained.
                original_error = getattr(exc, "orig", None)
                cause = getattr(original_error, "__cause__", None)
                diagnostic = getattr(original_error, "diag", None)
                primary = (
                    getattr(diagnostic, "message_primary", "")
                    or getattr(cause, "message", "")
                    or ""
                )
                symbol_match = re.search(r"([a-z_][a-z_0-9.]+)\([a-z_0-9, ]*\)", primary)
                operator_match = re.search(r"([a-z_]+ [<>=?@|#]+ [a-z_]+)", primary)
                symbol = (
                    symbol_match.group(1)
                    if symbol_match
                    else operator_match.group(1)
                    if operator_match
                    else None
                )
                constraint = getattr(cause, "constraint_name", None) or getattr(
                    diagnostic, "constraint_name", None
                )
                sqlstate = getattr(original_error, "sqlstate", None)
                if not isinstance(sqlstate, str) or re.fullmatch(r"[A-Z0-9]{5}", sqlstate) is None:
                    sqlstate = None
                if not isinstance(constraint, str) or not re.fullmatch(
                    r"[a-z_0-9]{1,120}", constraint
                ):
                    constraint = None
                print(
                    json.dumps(
                        {
                            "numeric_trial_phase": phase,
                            "category": category,
                            "line": line,
                            "constraint": constraint,
                            "sqlstate": sqlstate,
                            "symbol": symbol,
                            "frames": frames,
                        }
                    )
                )
                raise OriginalNumericProofTrialError(phase) from None
            finally:
                await outer.rollback()
                phase = "numeric_trial_rollback_failed"
                require(await inventory(connection) == before, "numeric_trial_original_changed")
                require(
                    await connection.scalar(
                        text(
                            "SELECT to_regclass('rag_generation_numeric_validations') IS NULL AND to_regprocedure('rag_require_generative_numeric_candidate(uuid,uuid)') IS NULL"
                        )
                    ),
                    "numeric_trial_ddl_survived",
                )
                if trial_complete:
                    legacy_execution = await connection.scalar(
                        text(
                            "SELECT execution_id FROM rag_generation_execution_audits WHERE configuration_version_id=:version AND actor_id=:actor AND status IN ('succeeded','allowed') AND execution_id IS NOT NULL LIMIT 1"
                        ),
                        {"version": trial.legacy_config_id, "actor": trial.actor},
                    )
                    legacy_sessions = async_sessionmaker(
                        connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                    )
                    async with legacy_sessions() as legacy_session:
                        require(
                            await SqlAlchemyNumericValidationRepository(
                                legacy_session
                            ).expected_context_for_execution(
                                actor_id=trial.actor, execution_id=legacy_execution
                            )
                            is None,
                            "numeric_trial_original_legacy_read_failed",
                        )
                await connection.rollback()
    except OriginalNumericProofTrialError:
        raise
    except Exception:
        raise OriginalNumericProofTrialError(phase) from None
    finally:
        await engine.dispose()
