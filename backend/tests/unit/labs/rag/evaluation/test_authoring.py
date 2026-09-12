from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError


def test_preview_scope_requires_explicit_unique_document_selection():
    from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringScope

    values = {"configuration_version_id": uuid4(), "workspace_ids": [uuid4()]}
    for invalid in [None, [], [uuid4()] * 2]:
        with pytest.raises(ValidationError):
            AuthoringScope(**values, asset_version_ids=invalid)
    with pytest.raises(ValidationError):
        AuthoringScope(**values, asset_version_ids=[uuid4()], complete=True)


@pytest.mark.parametrize("confirmed", [False, 0, 1, "true", None])
def test_run_requires_literal_boolean_retention_confirmation(confirmed):
    from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringRunRequest

    with pytest.raises(ValidationError):
        AuthoringRunRequest(
            configuration_version_id=uuid4(),
            workspace_ids=[uuid4()],
            asset_version_ids=[uuid4()],
            scope_sha256="a" * 64,
            draft_id=uuid4(),
            dataset_name="Synthetic evaluation",
            cases=[
                {
                    "id": uuid4(),
                    "query": "No known answer?",
                    "expected_answer_status": "insufficient_evidence",
                }
            ],
            retrieval_k=3,
            repetition_count=2,
            retention_confirmed=confirmed,
        )


def context_and_request():
    from ai_workshop.labs.rag.evaluation.authoring import AuthoringBuild, AuthoringContext
    from ai_workshop.labs.rag.evaluation.authoring_schemas import (
        AuthoringDocument,
        AuthoringEvidence,
        AuthoringRunRequest,
        AuthoringScope,
    )

    actor, workspace, document, asset, evidence, projection, build = [uuid4() for _ in range(7)]
    scope = AuthoringScope(
        configuration_version_id=uuid4(), workspace_ids=(workspace,), asset_version_ids=(asset,)
    )
    unit = AuthoringEvidence(
        id=evidence,
        document_id=document,
        asset_version_id=asset,
        projection_id=projection,
        index_build_id=build,
        text="가😀나다",
        element_id=uuid4(),
        start_char=10,
        end_char=14,
    )
    second = unit.model_copy(
        update={"id": uuid4(), "text": "다른 근거", "start_char": 20, "end_char": 25}
    )
    context = AuthoringContext(
        actor,
        scope,
        uuid4(),
        uuid4(),
        (
            AuthoringDocument(
                document_id=document,
                workspace_id=workspace,
                asset_version_id=asset,
                title="Synthetic",
                number=1,
                sha256="a" * 64,
            ),
        ),
        (unit, second),
        (AuthoringBuild(asset, projection, build, "physical-test-identity", 1, 768),),
    )
    request = AuthoringRunRequest(
        **scope.model_dump(),
        scope_sha256=context.preview().scope_sha256,
        draft_id=uuid4(),
        dataset_name="Synthetic evaluation",
        retrieval_k=3,
        repetition_count=2,
        retention_confirmed=True,
        cases=[
            {
                "id": uuid4(),
                "query": "😀의 의미?",
                "expected_answer_status": "supported",
                "expected_evidence_ids": [evidence],
                "expected_highlight": {
                    "kind": "keyword",
                    "document_id": document,
                    "asset_version_id": asset,
                    "evidence_unit_id": evidence,
                    "spans": [[11, 12]],
                },
            }
        ],
    )
    return context, request


def test_server_fixture_uses_complete_universe_and_codepoint_location():
    import json

    from ai_workshop.labs.rag.evaluation.authoring import build_fixture
    from ai_workshop.labs.rag.evaluation.domain import load_evaluation_dataset

    context, request = context_and_request()
    fixture = build_fixture(context, request, as_of="2026-09-09T00:00:00Z")
    dataset = load_evaluation_dataset(json.dumps(fixture, ensure_ascii=False).encode())
    assert dataset.cases[0].permission_scenario.authorized_source_ids == frozenset(
        unit.id for unit in context.evidence
    )
    assert dataset.cases[0].expected_evidence_ids == frozenset({context.evidence[0].id})
    assert dataset.cases[0].expected_highlight.spans[0].start == 11
    assert dataset.cases[0].expected_highlight.spans[0].end == 12
    assert dataset.id != request.draft_id
    assert dataset.cases[0].id != request.cases[0].id
    assert fixture == build_fixture(context, request, as_of="2026-09-09T00:00:00Z")
    other = replace(context, actor_id=uuid4())
    assert build_fixture(other, request, as_of="2026-09-09T00:00:00Z")["id"] != fixture["id"]


@pytest.mark.parametrize(
    "change",
    [
        {"spans": ((0, 1),)},
        {"spans": ((14, 15),)},
        {"spans": ((11, 11),)},
        {"spans": ((11, 12), (11, 13))},
        {"document_id": UUID(int=1)},
        {"page": 2},
        {"spans": (), "bboxes": ((0, 0, 1, 1),)},
    ],
)
def test_manual_highlight_must_match_real_source_location(change):
    from ai_workshop.labs.rag.evaluation.authoring import build_fixture
    from ai_workshop.shared.errors import AppError

    context, request = context_and_request()
    case = request.cases[0]
    bad = request.model_copy(
        update={
            "cases": (
                case.model_copy(
                    update={"expected_highlight": case.expected_highlight.model_copy(update=change)}
                ),
            )
        }
    )
    with pytest.raises(AppError) as caught:
        build_fixture(context, bad, as_of="2026-09-09T00:00:00Z")
    assert caught.value.code == "evaluation_authoring_invalid"


def test_preview_digest_binds_actor_physical_identity_and_evidence_but_not_order():
    context, _ = context_and_request()
    first = context.preview()
    assert replace(context, evidence=tuple(reversed(context.evidence))).preview() == first
    assert replace(context, actor_id=uuid4()).preview().scope_sha256 != first.scope_sha256
    assert (
        replace(context, builds=(replace(context.builds[0], index_uuid="replacement"),))
        .preview()
        .scope_sha256
        != first.scope_sha256
    )
    encoded = first.model_dump_json()
    assert "physical-test-identity" not in encoded
    assert "index_name" not in encoded
    assert first.complete is True


@pytest.mark.parametrize("field", ["query", "dataset_name"])
def test_authoring_text_rejects_non_utf8_surrogates(field):
    from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringRunRequest

    _, request = context_and_request()
    values = request.model_dump()
    if field == "query":
        values["cases"][0]["query"] = "\ud800"
    else:
        values[field] = "\ud800"
    with pytest.raises(ValidationError):
        AuthoringRunRequest.model_validate(values)


def test_forged_correct_evidence_never_enters_the_server_fixture():
    from ai_workshop.labs.rag.evaluation.authoring import build_fixture
    from ai_workshop.shared.errors import AppError

    context, request = context_and_request()
    case = request.cases[0].model_copy(update={"expected_evidence_ids": (uuid4(),)})
    with pytest.raises(AppError) as caught:
        build_fixture(
            context, request.model_copy(update={"cases": (case,)}), as_of="2026-09-09T00:00:00Z"
        )
    assert caught.value.code == "evaluation_authoring_invalid"


@pytest.mark.parametrize("operation", ["documents", "preview", "run"])
async def test_authoring_storage_errors_are_safe_and_rollback(operation):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy.exc import SQLAlchemyError

    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits, AuthoringService
    from ai_workshop.labs.rag.evaluation.authoring_schemas import AuthoringDocumentsRequest
    from ai_workshop.shared.errors import AppError

    context, request = context_and_request()
    failure = AsyncMock(side_effect=SQLAlchemyError("synthetic-storage-detail-not-public"))
    rollback = AsyncMock()
    repo = SimpleNamespace(documents=failure, resolve_scope=failure, lock_draft=failure)
    service = AuthoringService(repo, object(), limits=AuthoringLimits(), rollback=rollback)
    value = request if operation == "run" else context.scope
    if operation == "documents":
        value = AuthoringDocumentsRequest(
            configuration_version_id=context.scope.configuration_version_id,
            workspace_ids=context.scope.workspace_ids,
        )
    with pytest.raises(AppError) as caught:
        await getattr(service, operation)(context.actor_id, value)
    assert "synthetic-storage" not in caught.value.message
    assert caught.value.status_code == 409
    rollback.assert_awaited_once()


async def test_case_limit_is_enforced_before_repository_access():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from ai_workshop.labs.rag.evaluation.authoring import AuthoringLimits, AuthoringService
    from ai_workshop.shared.errors import AppError

    context, request = context_and_request()
    request = request.model_copy(
        update={"cases": (request.cases[0], request.cases[0].model_copy(update={"id": uuid4()}))}
    )
    repo = SimpleNamespace(lock_draft=AsyncMock())
    service = AuthoringService(
        repo, object(), limits=AuthoringLimits(max_cases=1), rollback=AsyncMock()
    )
    with pytest.raises(AppError) as caught:
        await service.run(context.actor_id, request)
    assert caught.value.code == "evaluation_authoring_too_large"
    repo.lock_draft.assert_not_awaited()
