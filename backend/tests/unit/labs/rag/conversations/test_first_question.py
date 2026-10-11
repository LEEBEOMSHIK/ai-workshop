"""First-question behavior: no eager conversations, stable replay and safe titles."""

import importlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.conversations import schemas
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.conversations.test_service import setup  # noqa: F401


@pytest.mark.parametrize(
    ("question", "title", "derivation"),
    [
        ("AM-LAB-840의 대금 지급일이 언제야?", "AM-LAB-840 대금 지급일 확인", "extracted"),
        (
            "파이썬 리스트와 튜플의 차이를 설명해 주세요",
            "파이썬 리스트와 튜플의 차이 설명",
            "extracted",
        ),
        ("CPU request와 limit을 비교해 주세요", "CPU request와 limit 비교", "extracted"),
        (
            "밤나무 뿌리와 잎의 역할을 각각 설명해 주세요",
            "밤나무 뿌리와 잎의 역할을 각각 설명",
            "extracted",
        ),
        (
            "백업을 삭제하지 않고 복원할 수 있나요?",
            "백업을 삭제하지 않고 복원할 수 있나요?",
            "preserved",
        ),
        ("그건 언제 돼요?", "새 대화", "fallback"),
        ("긴 배경 설명 " * 15 + "실제 요청을 설명해 주세요", "새 대화", "fallback"),
        (
            '"delete"와 `restore`를 비교해 주세요',
            '"delete"와 `restore`를 비교해 주세요',
            "preserved",
        ),
        (
            "정책을 설명해 주세요. 그리고 예외를 비교해 주세요",
            "정책을 설명해 주세요. 그리고 예외를 비교해 주세요",
            "preserved",
        ),
    ],
)
def test_first_question_title_preserves_subject_negation_and_multiple_requests(
    question, title, derivation
):
    assert (
        importlib.util.find_spec("ai_workshop.labs.rag.conversations.title_policy") is not None
    ), "The local first-question title policy is missing"
    policy = importlib.import_module("ai_workshop.labs.rag.conversations.title_policy")
    result = policy.derive_title(question, 64)
    assert (result.title, result.derivation) == (title, derivation)


def test_start_schema_accepts_no_revision_and_rejects_partial_draft_pair():
    assert hasattr(schemas, "ConversationStart"), "Atomic start request is missing"
    values = dict(
        request_id=uuid4(),
        query="Question?",
        connection_version_id=uuid4(),
        workspace_ids=[uuid4()],
    )
    request = schemas.ConversationStart(**values)
    assert request.draft_id is None and request.draft_revision is None
    for changes in (
        {"expected_revision": 1},
        {"draft_id": uuid4()},
        {"draft_revision": 1},
        {"query": "   "},
    ):
        with pytest.raises(ValidationError):
            schemas.ConversationStart(**(values | changes))


@pytest.mark.asyncio
async def test_start_replay_conflict_deleted_fence_and_single_execution(setup):  # noqa: F811
    service, repo, access, executor, actor, incoming = setup
    assert hasattr(service, "start"), "Atomic first-question start is missing"
    from tests.unit.labs.rag.conversations.start_support import attach_memory_starts

    attach_memory_starts(repo)
    request = schemas.ConversationStart(
        **incoming.model_dump(exclude={"expected_revision"}, exclude_none=True)
    )
    first = await service.start("demo", actor, request)
    assert len(repo.items) == 1 and len(first.turns) == 1
    assert first.title == "Question?" and first.title_origin == "auto"
    assert first.title_source_turn_id == first.turns[0].id
    replay = await service.start("demo", actor, request)
    assert replay == first and executor.execute.await_count == 1
    with pytest.raises(AppError) as conflict:
        await service.start("demo", actor, request.model_copy(update={"query": "Other question?"}))
    assert conflict.value.status_code == 409
    access.visible.return_value = False
    hidden = await service.start("demo", actor, request)
    assert hidden.title == "접근할 수 없는 대화" and hidden.turns[0].redacted
    assert (await service.list_for_actor("demo", actor))[0].title == "접근할 수 없는 대화"
    await service.delete("demo", actor, first.id, first.revision)
    with pytest.raises(AppError) as gone:
        await service.start("demo", actor, request)
    assert gone.value.status_code == 410
    assert len(repo.items) == 1 and executor.execute.await_count == 1


@pytest.mark.asyncio
async def test_start_scope_or_consent_rejection_never_creates_conversation(setup):  # noqa: F811
    service, repo, _, executor, actor, incoming = setup
    assert hasattr(service, "start"), "Atomic first-question start is missing"
    from tests.unit.labs.rag.conversations.start_support import attach_memory_starts

    attach_memory_starts(repo)
    request = schemas.ConversationStart(
        **incoming.model_dump(exclude={"expected_revision"}, exclude_none=True)
    )
    service.domains.resolve_search.side_effect = AppError("not_found", "Missing", 404)
    with pytest.raises(AppError):
        await service.start("demo", actor, request)
    assert repo.items == {} and executor.execute.await_count == 0
    service.domains.resolve_search.side_effect = None
    request = request.model_copy(
        update={
            "codex_input_approval": schemas.CodexInputApprovalRequest(
                classification="synthetic",
                consented=False,
                disclosure_version="codex-external-generation-v1",
            )
        }
    )
    with pytest.raises(AppError):
        await service.start("demo", actor, request)
    assert repo.items == {} and executor.execute.await_count == 0


@pytest.mark.asyncio
async def test_manual_title_persists_and_is_redacted_with_first_turn(setup):  # noqa: F811
    service, repo, access, _, actor, incoming = setup
    assert hasattr(service, "start"), "Atomic first-question start is missing"
    from tests.unit.labs.rag.conversations.start_support import attach_memory_starts

    attach_memory_starts(repo)
    request = schemas.ConversationStart(
        **incoming.model_dump(exclude={"expected_revision"}, exclude_none=True)
    )
    first = await service.start("demo", actor, request)
    renamed = await service.rename("demo", actor, first.id, "Chosen", first.revision)
    assert renamed.title == "Chosen" and renamed.title_origin == "manual"
    replay = await service.start("demo", actor, request)
    assert replay.title == "Chosen"
    access.visible.return_value = False
    assert (await service.detail("demo", actor, first.id)).title == "접근할 수 없는 대화"


@pytest.mark.asyncio
async def test_old_create_api_cannot_create_empty_session(setup):  # noqa: F811
    from types import SimpleNamespace

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from ai_workshop.labs.rag.conversations.api import get_conversation_service, router
    from ai_workshop.platform.identity.api import get_current_user
    from ai_workshop.shared.errors import register_error_handlers

    service, repo, _, _, actor, _ = setup
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    app.dependency_overrides[get_conversation_service] = lambda: service
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=actor)
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/v1/rag/domains/demo/conversations", json={})
    assert response.status_code == 410 and repo.items == {}


@pytest.mark.asyncio
async def test_provider_acceptance_policy_rejects_before_runtime_creation():
    from ai_workshop.labs.rag.search.schemas import SearchRequest
    from tests.unit.labs.rag.search.test_generation_policy_gate import (
        CONFIGURATION_ID,
        WORKSPACE_ID,
        PolicyDecision,
        _configuration,
        _service,
    )

    case = _service(
        configuration=_configuration(approval=None),
        decision=PolicyDecision(True, None, uuid4(), ()),
    )
    service = case[0]
    assert hasattr(service, "validate_acceptance"), "Acceptance preflight is missing"
    with pytest.raises(AppError):
        await service.validate_acceptance(
            actor_id=uuid4(),
            request=SearchRequest(
                query="Synthetic?",
                configuration_id=CONFIGURATION_ID,
                workspace_ids=[WORKSPACE_ID],
                experimental=True,
            ),
            configuration=_configuration(approval=None),
        )


@pytest.mark.asyncio
async def test_start_cannot_skip_missing_acceptance_adapter(setup):  # noqa: F811
    from tests.unit.labs.rag.conversations.start_support import attach_memory_starts

    service, repo, _, executor, actor, incoming = setup
    attach_memory_starts(repo)
    if hasattr(executor, "preflight"):
        del executor.preflight
    request = schemas.ConversationStart(
        **incoming.model_dump(exclude={"expected_revision"}, exclude_none=True)
    )
    with pytest.raises(AppError) as unavailable:
        await service.start("demo", actor, request)
    assert unavailable.value.code == "conversation_preflight_unavailable"
    assert repo.items == {} and executor.execute.await_count == 0


@pytest.mark.asyncio
async def test_retired_service_create_cannot_persist_an_empty_conversation(setup):  # noqa: F811
    service, repo, _, _, actor, _ = setup
    with pytest.raises(AppError) as retired:
        await service.create("demo", actor, None)
    assert retired.value.status_code == 410 and repo.items == {}
