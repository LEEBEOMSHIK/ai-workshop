"""Offline, reviewer-authored rubric checks; never a semantic correctness oracle.

This module is intentionally absent from live generation and database judgments.
Literal matches are necessary benchmark checks only, not entailment. A matched
rubric always remains unreviewed; a failed check is not proof a paraphrase is false.
"""

import hashlib
import json
import unicodedata
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Evidence(Value):
    evidence_id: UUID
    text: str = Field(min_length=1)


class Claim(Value):
    text: str = Field(min_length=1)
    evidence_ids: tuple[UUID, ...]


class Answer(Value):
    status: Literal["answered", "insufficient_evidence", "error"]
    answer: str
    claims: tuple[Claim, ...]
    citation_validation: Literal["passed", "failed", "not_applicable_no_claims"]


type Terms = tuple[tuple[str, ...], ...]


class Rule(Value):
    key: str = Field(min_length=1)
    terms: Terms
    support: tuple[Evidence, ...]


class Example(Value):
    key: str = Field(min_length=1)
    trigger_terms: Terms
    trigger_evidence_ids: tuple[UUID, ...]
    condition_terms: Terms
    support: tuple[Evidence, ...]


class Rubric(Value):
    version: int = Field(ge=1)
    rules: tuple[Rule, ...]
    examples: tuple[Example, ...] = ()

    @model_validator(mode="after")
    def validate_annotations(self) -> Self:
        if not self.rules:
            raise ValueError("A positive rubric requires a general rule.")
        annotations: tuple[Rule | Example, ...] = (*self.rules, *self.examples)
        if len({a.key for a in annotations}) != len(annotations):
            raise ValueError("Criterion keys must be unique.")
        for annotation in annotations:
            ids = tuple(e.evidence_id for e in annotation.support)
            if not ids or len(set(ids)) != len(ids):
                raise ValueError("Support bundles must be nonempty and unique.")
            groups = (
                (annotation.terms,)
                if isinstance(annotation, Rule)
                else (annotation.trigger_terms, annotation.condition_terms)
            )
            for terms in groups:
                if not terms or any(
                    not group or any(not t.strip() for t in group) for group in terms
                ):
                    raise ValueError("Every term group needs nonempty alternatives.")
            if isinstance(annotation, Example) and (
                not annotation.trigger_evidence_ids
                or not set(annotation.trigger_evidence_ids).issubset(ids)
            ):
                raise ValueError("Example triggers must be bound to their source bundle.")
        return self


class Finding(Value):
    code: str
    criterion: str | None = None
    claim_index: int | None = None


class Assessment(Value):
    check_version: Literal["offline-rubric-v1"] = "offline-rubric-v1"
    status: Literal["failed", "unreviewed", "invalid_input"]
    semantic_review_required: Literal[True] = True
    semantic_correctness: Literal["unreviewed"] = "unreviewed"
    findings: tuple[Finding, ...]
    rubric_digest: str
    input_digest: str


def assess(answer: Answer, rubric: Rubric, evidence: tuple[Evidence, ...]) -> Assessment:
    """Assess an already stored answer without I/O or generation."""
    invalid = _input_findings(answer, rubric, evidence)
    findings = invalid or _content_findings(answer, rubric)
    status: Literal["failed", "unreviewed", "invalid_input"] = "unreviewed"
    if invalid:
        status = "invalid_input"
    elif findings and answer.status != "error":
        status = "failed"
    return Assessment(
        status=status,
        findings=tuple(findings),
        rubric_digest=_digest(rubric.model_dump(mode="json")),
        input_digest=_digest(
            {
                "answer": answer.model_dump(mode="json"),
                "evidence": [item.model_dump(mode="json") for item in evidence],
            }
        ),
    )


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _matches(text: str, terms: Terms) -> bool:
    normalized = _normalized(text)
    return all(any(_normalized(term) in normalized for term in group) for group in terms)


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _input_findings(
    answer: Answer, rubric: Rubric, evidence: tuple[Evidence, ...]
) -> list[Finding]:
    findings: list[Finding] = []
    sources = {e.evidence_id: e.text for e in evidence}
    if len(sources) != len(evidence):
        findings.append(Finding(code="duplicate_evidence_id"))
    annotations: tuple[Rule | Example, ...] = (*rubric.rules, *rubric.examples)
    for annotation in annotations:
        if any(sources.get(q.evidence_id) != q.text for q in annotation.support):
            findings.append(Finding(code="source_binding_mismatch", criterion=annotation.key))
    # Never select whichever surface (answer or claims) produces a better score.
    if _normalized(answer.answer) != _normalized(" ".join(c.text for c in answer.claims)):
        findings.append(Finding(code="answer_claim_mismatch"))
    if answer.status != "answered" and (answer.answer or answer.claims):
        findings.append(Finding(code="status_content_mismatch"))
    for index, claim in enumerate(answer.claims):
        if len(set(claim.evidence_ids)) != len(claim.evidence_ids):
            findings.append(Finding(code="duplicate_citation_id", claim_index=index))
        if any(eid not in sources for eid in claim.evidence_ids):
            findings.append(Finding(code="unknown_citation_id", claim_index=index))
    return findings


def _supported(claim: Claim, support: tuple[Evidence, ...]) -> bool:
    # Conjunction within one claim, never a union of unrelated claims' citations.
    return {q.evidence_id for q in support}.issubset(claim.evidence_ids)


def _content_findings(answer: Answer, rubric: Rubric) -> list[Finding]:
    if answer.status == "error":
        return [Finding(code="execution_error_not_judged")]
    if answer.status != "answered":
        return [Finding(code="expected_answer_missing")]
    findings: list[Finding] = []
    if answer.citation_validation != "passed":
        findings.append(Finding(code="citation_validation_not_passed"))
    for rule in rubric.rules:
        matching = [claim for claim in answer.claims if _matches(claim.text, rule.terms)]
        if not matching:
            findings.append(Finding(code="required_rule_missing", criterion=rule.key))
        elif not any(_supported(claim, rule.support) for claim in matching):
            findings.append(Finding(code="rule_support_incomplete", criterion=rule.key))
    for index, claim in enumerate(answer.claims):
        if not claim.evidence_ids:
            findings.append(Finding(code="claim_citation_missing", claim_index=index))
        for example in rubric.examples:
            triggered = bool(set(claim.evidence_ids).intersection(example.trigger_evidence_ids))
            if not triggered and not _matches(claim.text, example.trigger_terms):
                continue
            if not _matches(claim.text, example.condition_terms):
                findings.append(
                    Finding(
                        code="example_condition_missing", criterion=example.key, claim_index=index
                    )
                )
            if not _supported(claim, example.support):
                findings.append(
                    Finding(
                        code="example_support_incomplete", criterion=example.key, claim_index=index
                    )
                )
    return findings
