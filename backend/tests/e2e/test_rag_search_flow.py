from asyncio import sleep
from collections.abc import Awaitable, Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from os import environ
from typing import Protocol, cast
from unittest.mock import patch
from uuid import UUID, uuid4

import pymupdf
import pytest
from celery import Celery  # type: ignore[import-untyped]
from elasticsearch import AsyncElasticsearch
from httpx import AsyncClient, MockTransport, Request, Response
from sqlalchemy import func, select

from ai_workshop.config import get_settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.configurations.domain import (
    BM25_BASELINE_ANSWER_POLICY_VERSION_ID,
    BM25_BASELINE_CONFIGURATION_ID,
    BM25_BASELINE_CONFIGURATION_VERSION_ID,
    BM25_BASELINE_NAME,
)
from ai_workshop.labs.rag.configurations.models import (
    AnswerPolicyVersionRecord,
    RagConfigurationRecord,
    RagConfigurationVersionRecord,
)
from ai_workshop.labs.rag.documents.models import (
    EvidenceUnitRecord,
    RagProjectionRecord,
    RetrievalChunkRecord,
    StructuralElementRecord,
)
from ai_workshop.labs.rag.evaluation.models import (
    EvaluationCaseResultRecord,
    EvaluationRunConfigurationRecord,
)
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.service import IndexingService
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.cli import bootstrap_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.identity.repository import SqlAlchemyUserRepository
from ai_workshop.platform.identity.service import Argon2PasswordHasher
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.domain import MembershipRole
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord
from ai_workshop.shared.db import create_engine, create_session_factory
from ai_workshop.worker import (
    RAG_ASSET_HANDOFF_RECONCILE_TASK,
    RAG_DISPATCH_RECONCILE_TASK,
    RAG_EVALUATION_DISPATCH_RECONCILE_TASK,
    create_celery,
)
from tools.e2e_runtime import E2ERuntimeContractError, validate_prepared_e2e

actual_stack = pytest.mark.skipif(
    environ.get("AI_WORKSHOP_E2E") != "1"
    or environ.get("AI_WORKSHOP_ENVIRONMENT") != "test",
    reason=(
        "RAG E2E tests require AI_WORKSHOP_E2E=1 and "
        "AI_WORKSHOP_ENVIRONMENT=test in the isolated smoke project."
    ),
)

PROFILE_ID = UUID("00000000-0000-0000-0000-00000000e201")
FIRST_BUILD_ID = UUID("00000000-0000-0000-0000-00000000e301")
SECOND_BUILD_ID = UUID("00000000-0000-0000-0000-00000000e302")
FIRST_PROJECTION_ID = UUID("00000000-0000-0000-0000-00000000e401")
SECOND_PROJECTION_ID = UUID("00000000-0000-0000-0000-00000000e402")
FIRST_CHUNK_ID = UUID("00000000-0000-0000-0000-00000000e501")
SECOND_CHUNK_ID = UUID("00000000-0000-0000-0000-00000000e502")

OWNER_EMAIL = "rag.owner.e2e@example.com"
MEMBER_EMAIL = "rag.member.e2e@example.com"
TEST_PASSWORD = "task14-public-synthetic-password"
INSUFFICIENT_QUERY = "ZXQJ987654321NOMATCH"
IMPORTED_E5_MODEL_ID = "00000000-0000-0000-0000-000000000101"
IMPORTED_E5_MODEL_CONFIG: dict[str, object] = {
    "repo_id": "intfloat/multilingual-e5-base",
    "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
    "dimension": 768,
    "max_tokens": 512,
    "query_prefix": "query: ",
    "document_prefix": "passage: ",
    "normalize": True,
    "device": "cpu",
    "dtype": "float32",
    "output_mode": "dense",
    "data_policy": "local_only",
}
RAG_PROJECTION_TASK_SEQUENCE = (
    RAG_ASSET_HANDOFF_RECONCILE_TASK,
    RAG_DISPATCH_RECONCILE_TASK,
)


class _TaskSender(Protocol):
    def send_task(
        self,
        name: str,
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> object: ...


def _document(
    *,
    chunk_id: UUID,
    projection_id: UUID,
    build_id: UUID,
    title: str,
) -> IndexDocument:
    return IndexDocument(
        chunk_id=chunk_id,
        projection_id=projection_id,
        asset_version_id=UUID(int=chunk_id.int + 100),
        workspace_id=UUID("00000000-0000-0000-0000-00000000e601"),
        folder_id=None,
        allowed_user_ids=(UUID("00000000-0000-0000-0000-00000000e701"),),
        status="ready",
        title=title,
        section_path=("Synthetic policy",),
        text=f"{title} is searchable public synthetic evidence.",
        evidence_units=(),
        embedding=(1.0, 0.0),
        index_build_id=build_id,
    )


@actual_stack
@pytest.mark.asyncio
async def test_ready_documents_remain_searchable_after_another_projection_activates(
    prepared_rag_stack: None,
) -> None:
    """A profile-wide active search view must retain every READY document."""
    del prepared_rag_stack
    settings = get_settings()
    client = create_elasticsearch(settings)
    descriptor = IndexDescriptor(vector_dimension=2, similarity="cosine")
    service = IndexingService(
        ElasticsearchSearchIndex(client),
        index_prefix=settings.elasticsearch_index_prefix,
    )
    first = _document(
        chunk_id=FIRST_CHUNK_ID,
        projection_id=FIRST_PROJECTION_ID,
        build_id=FIRST_BUILD_ID,
        title="Existing policy",
    )
    second = replace(
        _document(
            chunk_id=SECOND_CHUNK_ID,
            projection_id=SECOND_PROJECTION_ID,
            build_id=SECOND_BUILD_ID,
            title="New policy",
        ),
        embedding=(0.0, 1.0),
    )
    concrete_indices = (
        descriptor.concrete_index_name(
            settings.elasticsearch_index_prefix, PROFILE_ID, FIRST_BUILD_ID
        ),
        descriptor.concrete_index_name(
            settings.elasticsearch_index_prefix, PROFILE_ID, SECOND_BUILD_ID
        ),
    )
    alias = descriptor.active_alias(settings.elasticsearch_index_prefix, PROFILE_ID)

    try:
        await service.index_projection(
            descriptor=descriptor,
            profile_id=PROFILE_ID,
            build_id=FIRST_BUILD_ID,
            projection_id=FIRST_PROJECTION_ID,
            expected_chunk_count=1,
            documents=(first,),
        )
        await service.index_projection(
            descriptor=descriptor,
            profile_id=PROFILE_ID,
            build_id=SECOND_BUILD_ID,
            projection_id=SECOND_PROJECTION_ID,
            expected_chunk_count=1,
            documents=(second,),
        )

        response = await client.search(
            index=alias,
            query={"match_all": {}},
            size=10,
            source_includes=("chunk_id",),
        )
        observed_chunk_ids = {
            UUID(hit["_source"]["chunk_id"])
            for hit in response["hits"]["hits"]
        }

        assert observed_chunk_ids == {FIRST_CHUNK_ID, SECOND_CHUNK_ID}
    finally:
        await _delete_stack_indices_and_close(client, concrete_indices)


async def _delete_stack_indices_and_close(
    client: AsyncElasticsearch,
    concrete_indices: Sequence[str],
) -> None:
    try:
        await client.indices.delete(
            index=list(concrete_indices),
            ignore_unavailable=True,
        )
    finally:
        await client.close()


@pytest.fixture
def prepared_rag_stack() -> None:
    try:
        validate_prepared_e2e(get_settings(), environ)
    except E2ERuntimeContractError as exc:
        pytest.fail(str(exc))
    if not environ.get("AI_WORKSHOP_E2E_BASE_URL"):
        pytest.fail("Prepared E2E requires scripts/smoke.ps1.")


def _remote_client() -> AsyncClient:
    base_url = environ["AI_WORKSHOP_E2E_BASE_URL"]
    return AsyncClient(base_url=base_url, timeout=30.0)


async def _login(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 200


async def _wait_for_job(client: AsyncClient, job_id: object) -> dict[str, object]:
    latest: dict[str, object] | None = None
    for _attempt in range(240):
        response = await client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest["status"] in {"succeeded", "failed"}:
            return latest
        await sleep(0.25)
    pytest.fail(
        "Asset verification did not finish: "
        f"job_id={job_id}, status={latest and latest.get('status')}"
    )


async def _create_workspace(
    client: AsyncClient, *, name: str, kind: str
) -> dict[str, object]:
    response = await client.post(
        "/api/v1/workspaces",
        json={"name": name, "kind": kind, "expires_at": None},
    )
    assert response.status_code == 201
    return response.json()


async def _get_or_create_personal_workspace(
    client: AsyncClient, *, name: str
) -> dict[str, object]:
    response = await client.get("/api/v1/workspaces")
    assert response.status_code == 200
    personal = [item for item in response.json() if item["kind"] == "personal"]
    assert len(personal) <= 1
    if personal:
        return personal[0]
    return await _create_workspace(client, name=name, kind="personal")


async def _upload(
    client: AsyncClient,
    workspace_id: object,
    *,
    name: str,
    media_type: str,
    content: bytes,
) -> tuple[dict[str, object], dict[str, object]]:
    response = await client.post(
        f"/api/v1/workspaces/{workspace_id}/documents",
        files={"file": (name, content, media_type)},
    )
    assert response.status_code == 201
    document = response.json()
    job = await _wait_for_job(client, document["job_id"])
    assert job["status"] == "succeeded"
    versions = await client.get(f"/api/v1/documents/{document['id']}/versions")
    assert versions.status_code == 200
    version = versions.json()[-1]
    assert version["status"] == "ready"
    return document, version


def _text_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page(width=420, height=240)
    page.insert_text((36, 54), "PUBLIC-LIQUIDITY-WINDOW-PDF is 14 calendar days.")
    page.insert_text((36, 90), "Synthetic public portfolio operations evidence.")
    content = document.tobytes()
    document.close()
    return content


async def _verify_stored_object(asset_version_id: object, expected: bytes) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            record = await session.get(AssetVersionRecord, UUID(str(asset_version_id)))
            assert record is not None
            object_key = record.object_key
            stored_sha256 = record.sha256
        stored = bytearray()
        async for chunk in LocalObjectStore(settings.object_store_root).open(object_key):
            stored.extend(chunk)
        assert bytes(stored) == expected
        assert stored_sha256 == sha256(expected).hexdigest()
    finally:
        await engine.dispose()


async def _seed_member_and_membership(workspace_id: object) -> UUID:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    member = User.create_owner(
        display_name="RAG Company Reader",
        email=MEMBER_EMAIL,
        password_hash=Argon2PasswordHasher().hash(TEST_PASSWORD),
    )
    try:
        async with sessions.begin() as session:
            await SqlAlchemyUserRepository(session).add(member)
            session.add(
                WorkspaceMembershipRecord(
                    workspace_id=UUID(str(workspace_id)),
                    user_id=member.id,
                    role=MembershipRole.MEMBER,
                )
            )
    finally:
        await engine.dispose()
    return member.id


async def _register_rag_components(
    client: AsyncClient,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    model_response = await client.get("/api/v1/rag/models")
    assert model_response.status_code == 200
    model = _select_imported_e5_model(model_response.json())
    indexing_response = await client.post(
        "/api/v1/rag/profiles/indexing",
        json={
            "name": "task14-e5-structure-aware",
            "version": 2,
            "config": {
                "chunker": {
                    "name": "structure-aware",
                    "version": 2,
                    "target_tokens": 380,
                    "overlap_tokens": 60,
                },
                "embedding": {"batch_size": 32, "similarity": "cosine"},
            },
            "bindings": [{"role": "embedding", "model_id": model["id"]}],
            "evaluation_state": "draft",
        },
    )
    assert indexing_response.status_code == 201
    indexing = indexing_response.json()

    async def retrieval(name: str, *, dense: bool) -> dict[str, object]:
        config: dict[str, object] = {
            "bm25": {"analyzer": "standard", "top_k": 30},
            "indexing_profile_id": indexing["id"],
        }
        if dense:
            config.update(
                {
                    "dense": {"top_k": 30},
                    "rrf": {"k": 60},
                    "reranker": {"enabled": False},
                }
            )
        response = await client.post(
            "/api/v1/rag/profiles/retrieval",
            json={
                "name": name,
                "version": 1,
                "config": config,
                "bindings": [],
                "evaluation_state": "draft",
            },
        )
        assert response.status_code == 201
        return response.json()

    bm25 = await retrieval("task14-bm25-baseline", dense=False)
    hybrid = await retrieval("task14-e5-hybrid-rrf", dense=True)
    await _seed_system_baseline(
        UUID(str(indexing["id"])), UUID(str(bm25["id"]))
    )
    return indexing, bm25, hybrid


async def _seed_system_baseline(indexing_profile_id: UUID, retrieval_profile_id: UUID) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            session.add(
                RagConfigurationRecord(
                    id=BM25_BASELINE_CONFIGURATION_ID,
                    owner_id=None,
                    name=BM25_BASELINE_NAME,
                    is_system=True,
                )
            )
            await session.flush()
            session.add(
                AnswerPolicyVersionRecord(
                    id=BM25_BASELINE_ANSWER_POLICY_VERSION_ID,
                    configuration_id=BM25_BASELINE_CONFIGURATION_ID,
                    version=1,
                    mode="extractive",
                    min_semantic_score=0.0,
                    min_keyword_coverage=0.5,
                    require_complete_provenance=True,
                    conflict_mode="separate_sources",
                )
            )
            await session.flush()
            session.add(
                RagConfigurationVersionRecord(
                    id=BM25_BASELINE_CONFIGURATION_VERSION_ID,
                    configuration_id=BM25_BASELINE_CONFIGURATION_ID,
                    version=1,
                    indexing_profile_id=indexing_profile_id,
                    retrieval_profile_id=retrieval_profile_id,
                    generation_profile_id=None,
                    answer_policy_version_id=BM25_BASELINE_ANSWER_POLICY_VERSION_ID,
                    evaluation_state="pending",
                    is_default=False,
                )
            )
    finally:
        await engine.dispose()


def test_projection_failure_diagnostics_are_safe_and_bounded() -> None:
    rows = [
        (
            UUID(int=ordinal + 1),
            UUID(int=ordinal + 101),
            UUID(int=ordinal + 201),
            "embedding",
            "running",
            "embedding",
            "model_cache_missing",
        )
        for ordinal in range(25)
    ]

    diagnostics = _projection_diagnostics(rows)

    assert len(diagnostics) == 20
    assert all(
        set(item)
        == {
            "asset_version_id",
            "projection_id",
            "job_id",
            "projection_status",
            "job_status",
            "job_stage",
            "error_code",
        }
        for item in diagnostics
    )
    assert all("error_message" not in item for item in diagnostics)


def test_search_payload_serializes_uuid_ids_for_the_api_contract() -> None:
    payload = _search_payload(
        query="synthetic query",
        configuration_id=UUID("00000000-0000-0000-0000-000000000501"),
        workspace_ids=[UUID("00000000-0000-0000-0000-000000000601")],
        experimental=True,
    )

    assert payload == {
        "query": "synthetic query",
        "configuration_id": "00000000-0000-0000-0000-000000000501",
        "workspace_ids": ["00000000-0000-0000-0000-000000000601"],
        "folder_ids": [],
        "top_k": 10,
        "experimental": True,
    }


def test_select_imported_e5_model_requires_the_exact_committed_definition() -> None:
    expected = {
        "id": "00000000-0000-0000-0000-000000000101",
        "kind": "embedding",
        "name": "multilingual-e5-base",
        "version": 1,
        "config": {
            "repo_id": "intfloat/multilingual-e5-base",
            "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
            "dimension": 768,
            "max_tokens": 512,
            "query_prefix": "query: ",
            "document_prefix": "passage: ",
            "normalize": True,
            "device": "cpu",
            "dtype": "float32",
            "output_mode": "dense",
            "data_policy": "local_only",
        },
    }

    selected = _select_imported_e5_model(
        [
            {
                "id": "00000000-0000-0000-0000-000000000999",
                "kind": "embedding",
                "name": "other-model",
                "version": 1,
                "config": {},
            },
            expected,
        ]
    )

    assert selected == expected


def test_evaluation_case_uses_independent_ground_truth_coordinates() -> None:
    case = _evaluation_case(
        query="COMPANY-RISK-CODE-AX17",
        ground_truth={
            "document_id": "00000000-0000-0000-0000-000000000701",
            "asset_version_id": "00000000-0000-0000-0000-000000000702",
            "evidence_unit_id": "00000000-0000-0000-0000-000000000703",
            "text": "COMPANY-RISK-CODE-AX17 requires daily compliance review.",
            "page": None,
            "char_start": 101,
            "char_end": 159,
            "bbox": None,
        },
        company_workspace_id="00000000-0000-0000-0000-000000000704",
        authorized_source_ids=["00000000-0000-0000-0000-000000000703"],
        forbidden_source_ids=["00000000-0000-0000-0000-000000000705"],
        as_of="2026-09-01T00:00:00Z",
    )

    assert case["expected"] == {
        "answer_status": "supported",
        "evidence_unit_ids": ["00000000-0000-0000-0000-000000000703"],
        "highlight": {
            "surface": "answer",
            "document_id": "00000000-0000-0000-0000-000000000701",
            "asset_version_id": "00000000-0000-0000-0000-000000000702",
            "evidence_unit_id": "00000000-0000-0000-0000-000000000703",
            "page": None,
            "kind": "keyword",
            "spans": [[101, 123]],
            "bboxes": [],
        },
    }


def test_grounded_answer_check_rejects_any_source_provenance_mismatch() -> None:
    ground_truth = {
        "workspace_id": "00000000-0000-0000-0000-000000000801",
        "document_id": "00000000-0000-0000-0000-000000000802",
        "asset_version_id": "00000000-0000-0000-0000-000000000803",
        "asset_version_number": 2,
        "projection_id": "00000000-0000-0000-0000-000000000804",
        "chunk_id": "00000000-0000-0000-0000-000000000805",
        "evidence_unit_id": "00000000-0000-0000-0000-000000000806",
        "element_id": "00000000-0000-0000-0000-000000000807",
        "title": "public-risk-policy.md",
        "media_type": "text/markdown",
        "section_path": ["Public Risk Policy"],
        "text": "COMPANY-RISK-CODE-AX17 requires daily compliance review.",
        "page": None,
        "char_start": 22,
        "char_end": 80,
        "bbox": None,
    }
    answer = {
        "excerpt": ground_truth["text"],
        "source": {
            "document_id": ground_truth["document_id"],
            "asset_version_id": ground_truth["asset_version_id"],
            "asset_version_number": 2,
            "workspace_id": ground_truth["workspace_id"],
            "folder_id": None,
            "projection_id": ground_truth["projection_id"],
            "chunk_id": ground_truth["chunk_id"],
            "evidence_unit_id": ground_truth["evidence_unit_id"],
            "element_id": ground_truth["element_id"],
            "title": ground_truth["title"],
            "media_type": ground_truth["media_type"],
            "section_path": ground_truth["section_path"],
            "location": {
                "element_id": ground_truth["element_id"],
                "page": None,
                "char_start": 22,
                "char_end": 80,
                "bbox": None,
            },
        },
        "highlights": [
            {
                "kind": "keyword",
                "evidence_unit_id": ground_truth["evidence_unit_id"],
                "text": "COMPANY",
                "char_start": 22,
                "char_end": 29,
                "page": None,
                "bbox": None,
                "score": None,
                "warnings": [],
            }
        ],
    }
    expected_highlights = [
        {
            "kind": "keyword",
            "evidence_unit_id": ground_truth["evidence_unit_id"],
            "text": "COMPANY",
            "char_start": 22,
            "char_end": 29,
            "page": None,
            "bbox": None,
            "score": None,
            "warnings": [],
        }
    ]

    _assert_grounded_answer(
        answer,
        ground_truth=ground_truth,
        expected_excerpt=ground_truth["text"],
        expected_highlights=expected_highlights,
    )
    mismatched = deepcopy(answer)
    mismatched["source"]["workspace_id"] = "00000000-0000-0000-0000-000000000899"
    with pytest.raises(AssertionError):
        _assert_grounded_answer(
            mismatched,
            ground_truth=ground_truth,
            expected_excerpt=ground_truth["text"],
            expected_highlights=expected_highlights,
        )


def test_private_leak_values_include_every_durable_provenance_identity() -> None:
    values = _private_leak_values(
        workspace_id="workspace-private",
        document_id="document-private",
        asset_version_id="version-private",
        projection_id="projection-private",
        chunk_ids=["chunk-one", "chunk-two"],
        evidence_unit_ids=["evidence-one", "evidence-two"],
        element_ids=["element-one", "element-two"],
        title="private-owner-note.txt",
        marker="PRIVATE-OWNER-MARKER-Q91",
    )

    assert values == (
        "workspace-private",
        "document-private",
        "version-private",
        "projection-private",
        "chunk-one",
        "chunk-two",
        "evidence-one",
        "evidence-two",
        "element-one",
        "element-two",
        "private-owner-note.txt",
        "PRIVATE-OWNER-MARKER-Q91",
    )


def test_standalone_system_baseline_seed_loads_profile_metadata() -> None:
    assert ProfileRecord.__table__ is RagConfigurationVersionRecord.metadata.tables[
        "rag_profiles"
    ]


def test_prepared_state_enqueues_registered_tasks_in_production_order() -> None:
    class RecordingCelery:
        def __init__(self) -> None:
            self.calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

        def send_task(
            self,
            name: str,
            args: tuple[object, ...],
            kwargs: dict[str, object],
        ) -> None:
            self.calls.append((name, args, kwargs))

    application = RecordingCelery()
    for task_name in RAG_PROJECTION_TASK_SEQUENCE:
        _enqueue_registered_task(application, task_name)
    _enqueue_registered_task(application, RAG_EVALUATION_DISPATCH_RECONCILE_TASK)

    assert application.calls == [
        ("ai_workshop.rag.reconcile_asset_handoffs", (), {}),
        ("ai_workshop.rag.reconcile_dispatches", (), {}),
        ("ai_workshop.rag.reconcile_evaluation_dispatches", (), {}),
    ]


def test_evaluation_failure_presence_never_copies_durable_error_text() -> None:
    assert _bounded_candidate_failures(None) == []
    assert _bounded_candidate_failures("synthetic private error body") == [
        "failure_present"
    ]


def test_insufficient_query_is_one_opaque_term_absent_from_the_corpus() -> None:
    corpus = (
        "COMPANY-RISK-CODE-AX17 requires daily compliance review.",
        "Investors must submit redemption notice five business days before payout.",
        "PRIVATE-OWNER-MARKER-Q91 is a synthetic personal research note.",
        "PUBLIC-LIQUIDITY-WINDOW-PDF is 14 calendar days.",
    )

    assert INSUFFICIENT_QUERY.isascii()
    assert INSUFFICIENT_QUERY.isalnum()
    assert all(INSUFFICIENT_QUERY.casefold() not in item.casefold() for item in corpus)


@pytest.mark.asyncio
async def test_prepared_owner_reuses_only_the_known_singleton_owner_condition() -> None:
    async def existing_owner(_name: str, _email: str) -> None:
        raise SystemExit("An owner already exists.")

    async def unexpected_failure(_name: str, _email: str) -> None:
        raise SystemExit("unexpected bootstrap failure")

    await _prepare_known_owner(bootstrap=existing_owner)
    with pytest.raises(SystemExit, match="unexpected bootstrap failure"):
        await _prepare_known_owner(bootstrap=unexpected_failure)


@pytest.mark.asyncio
async def test_prepared_personal_workspace_reuses_publicly_listed_workspace() -> None:
    requests: list[tuple[str, str]] = []

    async def handler(request: Request) -> Response:
        requests.append((request.method, request.url.path))
        return Response(
            200,
            json=[{"id": "known-personal", "kind": "personal"}],
        )

    async with AsyncClient(
        transport=MockTransport(handler), base_url="http://test"
    ) as client:
        workspace = await _get_or_create_personal_workspace(
            client, name="Task 14 Owner Notes"
        )

    assert workspace == {"id": "known-personal", "kind": "personal"}
    assert requests == [("GET", "/api/v1/workspaces")]


def test_expected_snapshot_pairs_fail_closed_on_duplicate_asset_versions() -> None:
    document_one = uuid4()
    document_two = uuid4()
    version = uuid4()

    assert _expected_snapshot_pairs({document_one: version}) == {(document_one, version)}
    with pytest.raises(AssertionError):
        _expected_snapshot_pairs({document_one: version, document_two: version})


@pytest.mark.asyncio
async def test_stack_index_cleanup_closes_client_when_index_delete_fails() -> None:
    class FailingIndices:
        async def delete(self, **_kwargs: object) -> None:
            raise RuntimeError("synthetic delete failure")

    class Client:
        indices = FailingIndices()
        closed = False

        async def close(self) -> None:
            self.closed = True

    client = Client()

    with pytest.raises(RuntimeError, match="synthetic delete failure"):
        await _delete_stack_indices_and_close(
            cast(AsyncElasticsearch, client),
            ("synthetic-index",),
        )

    assert client.closed is True


def _projection_diagnostics(
    rows: Sequence[Sequence[object]],
) -> list[dict[str, str | None]]:
    return [
        {
            "asset_version_id": str(row[0]),
            "projection_id": str(row[1]),
            "job_id": str(row[2]),
            "projection_status": str(row[3]),
            "job_status": str(row[4]),
            "job_stage": str(row[5]),
            "error_code": str(row[6]) if row[6] is not None else None,
        }
        for row in rows[:20]
    ]


def _select_imported_e5_model(
    models: Sequence[dict[str, object]],
) -> dict[str, object]:
    matching = [
        item
        for item in models
        if item
        == {
            "id": IMPORTED_E5_MODEL_ID,
            "kind": "embedding",
            "name": "multilingual-e5-base",
            "version": 1,
            "config": IMPORTED_E5_MODEL_CONFIG,
        }
    ]
    assert len(matching) == 1, "The exact committed multilingual E5 model must be imported."
    return matching[0]


def _evaluation_case(
    *,
    query: str,
    ground_truth: Mapping[str, object],
    company_workspace_id: object,
    authorized_source_ids: Sequence[object],
    forbidden_source_ids: Sequence[object],
    as_of: str,
) -> dict[str, object]:
    expected_text = str(ground_truth["text"])
    relative_start = expected_text.index(query)
    absolute_start = int(ground_truth["char_start"]) + relative_start
    absolute_end = absolute_start + len(query)
    return {
        "id": str(uuid4()),
        "kind": "exact_code",
        "query": query,
        "query_sha256": sha256(query.encode()).hexdigest(),
        "permission_scenario": {
            "name": "task14-company-owner",
            "actor": "caller",
            "workspace_ids": [str(company_workspace_id)],
            "folder_ids": [],
            "authorized_source_ids": sorted(str(item) for item in authorized_source_ids),
            "forbidden_source_ids": sorted(str(item) for item in forbidden_source_ids),
            "as_of": as_of,
        },
        "expected": {
            "answer_status": "supported",
            "evidence_unit_ids": [str(ground_truth["evidence_unit_id"])],
            "highlight": {
                "surface": "answer",
                "document_id": str(ground_truth["document_id"]),
                "asset_version_id": str(ground_truth["asset_version_id"]),
                "evidence_unit_id": str(ground_truth["evidence_unit_id"]),
                "page": ground_truth["page"],
                "kind": "keyword",
                "spans": [[absolute_start, absolute_end]],
                "bboxes": [],
            },
        },
    }


def _assert_grounded_answer(
    answer: Mapping[str, object],
    *,
    ground_truth: Mapping[str, object],
    expected_excerpt: object,
    expected_highlights: Sequence[Mapping[str, object]],
) -> None:
    assert answer["excerpt"] == expected_excerpt
    assert answer["source"] == {
        "document_id": str(ground_truth["document_id"]),
        "asset_version_id": str(ground_truth["asset_version_id"]),
        "asset_version_number": ground_truth["asset_version_number"],
        "workspace_id": str(ground_truth["workspace_id"]),
        "folder_id": ground_truth.get("folder_id"),
        "projection_id": str(ground_truth["projection_id"]),
        "chunk_id": str(ground_truth["chunk_id"]),
        "evidence_unit_id": str(ground_truth["evidence_unit_id"]),
        "element_id": str(ground_truth["element_id"]),
        "title": ground_truth["title"],
        "media_type": ground_truth["media_type"],
        "section_path": ground_truth["section_path"],
        "location": {
            "element_id": str(ground_truth["element_id"]),
            "page": ground_truth["page"],
            "char_start": ground_truth["char_start"],
            "char_end": ground_truth["char_end"],
            "bbox": ground_truth["bbox"],
        },
    }
    highlights = answer["highlights"]
    assert isinstance(highlights, list)
    assert len(highlights) == len(expected_highlights)
    for actual, expected in zip(highlights, expected_highlights, strict=True):
        assert isinstance(actual, dict)
        assert all(actual.get(key) == value for key, value in expected.items())
        if expected["kind"] == "semantic":
            assert isinstance(actual.get("score"), float)
        else:
            assert actual.get("score") is None


def _private_leak_values(
    *,
    workspace_id: object,
    document_id: object,
    asset_version_id: object,
    projection_id: object,
    chunk_ids: Sequence[object],
    evidence_unit_ids: Sequence[object],
    element_ids: Sequence[object],
    title: str,
    marker: str,
) -> tuple[str, ...]:
    return tuple(
        str(item)
        for item in (
            workspace_id,
            document_id,
            asset_version_id,
            projection_id,
            *chunk_ids,
            *evidence_unit_ids,
            *element_ids,
            title,
            marker,
        )
    )


def _enqueue_registered_task(
    application: _TaskSender,
    task_name: str,
) -> None:
    application.send_task(task_name, args=(), kwargs={})


async def _prepare_ready_projections(
    asset_version_ids: list[object],
    indexing_profile_id: object,
) -> dict[str, str]:
    application = _broker_task_sender()
    try:
        _enqueue_registered_task(application, RAG_PROJECTION_TASK_SEQUENCE[0])
        await _wait_for_queued_projections(asset_version_ids, indexing_profile_id)
        _enqueue_registered_task(application, RAG_PROJECTION_TASK_SEQUENCE[1])
        return await _wait_for_ready_projections(
            asset_version_ids,
            indexing_profile_id,
        )
    finally:
        application.close()


async def _wait_for_queued_projections(
    asset_version_ids: list[object],
    indexing_profile_id: object,
) -> None:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    expected = {UUID(str(item)) for item in asset_version_ids}
    latest: list[tuple[object, ...]] = []
    try:
        for _attempt in range(60):
            async with sessions() as session:
                latest = [
                    tuple(item)
                    for item in (
                        await session.execute(
                            select(
                                RagProjectionRecord.asset_version_id,
                                RagProjectionRecord.id,
                                RagIngestionJobRecord.job_id,
                                RagProjectionRecord.status,
                                JobRecord.status,
                                JobRecord.stage,
                                JobRecord.error_code,
                            )
                            .join(
                                RagIngestionJobRecord,
                                RagIngestionJobRecord.projection_id
                                == RagProjectionRecord.id,
                            )
                            .join(
                                JobRecord,
                                JobRecord.id == RagIngestionJobRecord.job_id,
                            )
                            .where(
                                RagProjectionRecord.asset_version_id.in_(expected),
                                RagProjectionRecord.indexing_profile_id
                                == UUID(str(indexing_profile_id)),
                            )
                            .order_by(RagProjectionRecord.asset_version_id)
                        )
                    ).all()
                ]
            if {item[0] for item in latest} == expected:
                return
            await sleep(1)
        pytest.fail(
            "RAG handoff did not create durable queued projections: "
            f"{_projection_diagnostics(latest)}"
        )
    finally:
        await engine.dispose()


def _dispatch_pending_evaluation() -> None:
    application = _broker_task_sender()
    try:
        _enqueue_registered_task(
            application,
            RAG_EVALUATION_DISPATCH_RECONCILE_TASK,
        )
    finally:
        application.close()


def _broker_task_sender() -> Celery:
    application = create_celery(get_settings())
    application.conf.task_always_eager = False
    return application


def _bounded_candidate_failures(failure: object) -> list[str]:
    return [] if failure is None else ["failure_present"]


async def _load_evaluation_candidate_ground_truth(
    *,
    run_id: object,
    expected_configuration_version_ids: Sequence[object],
) -> dict[str, dict[str, object]]:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    expected = {UUID(str(item)) for item in expected_configuration_version_ids}
    try:
        async with sessions() as session:
            rows = (
                await session.execute(
                    select(
                        EvaluationRunConfigurationRecord.configuration_version_id,
                        EvaluationRunConfigurationRecord.status,
                        EvaluationRunConfigurationRecord.failure,
                        func.count(EvaluationCaseResultRecord.id),
                    )
                    .outerjoin(
                        EvaluationCaseResultRecord,
                        EvaluationCaseResultRecord.run_configuration_id
                        == EvaluationRunConfigurationRecord.id,
                    )
                    .where(
                        EvaluationRunConfigurationRecord.run_id
                        == UUID(str(run_id)),
                        EvaluationRunConfigurationRecord.configuration_version_id.in_(
                            expected
                        ),
                    )
                    .group_by(
                        EvaluationRunConfigurationRecord.configuration_version_id,
                        EvaluationRunConfigurationRecord.status,
                        EvaluationRunConfigurationRecord.failure,
                    )
                )
            ).all()
        assert {row[0] for row in rows} == expected
        return {
            str(row[0]): {
                "status": str(row[1]),
                "failures": _bounded_candidate_failures(row[2]),
                "case_result_count": int(row[3]),
            }
            for row in rows
        }
    finally:
        await engine.dispose()


async def _load_ground_truth(
    *,
    document_id: object,
    asset_version_id: object,
    projection_id: object,
    expected_text: str,
) -> dict[str, object]:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            rows = (
                await session.execute(
                    select(
                        DocumentRecord.workspace_id,
                        DocumentRecord.id,
                        DocumentRecord.folder_id,
                        DocumentRecord.name,
                        AssetVersionRecord.id,
                        AssetVersionRecord.number,
                        AssetVersionRecord.media_type,
                        RagProjectionRecord.id,
                        RetrievalChunkRecord.id,
                        RetrievalChunkRecord.section_path,
                        EvidenceUnitRecord.id,
                        EvidenceUnitRecord.text,
                        StructuralElementRecord.id,
                        StructuralElementRecord.text,
                        StructuralElementRecord.section_path,
                        EvidenceUnitRecord.page,
                        EvidenceUnitRecord.char_start,
                        EvidenceUnitRecord.char_end,
                        EvidenceUnitRecord.bbox,
                    )
                    .select_from(DocumentRecord)
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.document_id == DocumentRecord.id,
                    )
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.asset_version_id == AssetVersionRecord.id,
                    )
                    .join(
                        RetrievalChunkRecord,
                        RetrievalChunkRecord.projection_id == RagProjectionRecord.id,
                    )
                    .join(
                        EvidenceUnitRecord,
                        EvidenceUnitRecord.retrieval_chunk_id
                        == RetrievalChunkRecord.id,
                    )
                    .join(
                        StructuralElementRecord,
                        StructuralElementRecord.id == EvidenceUnitRecord.element_id,
                    )
                    .where(
                        DocumentRecord.id == UUID(str(document_id)),
                        DocumentRecord.active_version_id
                        == UUID(str(asset_version_id)),
                        AssetVersionRecord.id == UUID(str(asset_version_id)),
                        RagProjectionRecord.id == UUID(str(projection_id)),
                        EvidenceUnitRecord.text == expected_text,
                        StructuralElementRecord.text == expected_text,
                    )
                )
            ).all()
        assert len(rows) == 1, "Expected one exact durable evidence provenance row."
        row = rows[0]
        return {
            "workspace_id": str(row[0]),
            "document_id": str(row[1]),
            "folder_id": str(row[2]) if row[2] is not None else None,
            "title": row[3],
            "asset_version_id": str(row[4]),
            "asset_version_number": row[5],
            "media_type": row[6],
            "projection_id": str(row[7]),
            "chunk_id": str(row[8]),
            "section_path": row[9],
            "evidence_unit_id": str(row[10]),
            "text": row[11],
            "element_id": str(row[12]),
            "element_text": row[13],
            "element_section_path": row[14],
            "page": row[15],
            "char_start": row[16],
            "char_end": row[17],
            "bbox": row[18],
        }
    finally:
        await engine.dispose()


async def _load_private_leak_values(
    *,
    workspace_id: object,
    document_id: object,
    asset_version_id: object,
    projection_id: object,
    title: str,
    marker: str,
) -> tuple[str, ...]:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    projection_uuid = UUID(str(projection_id))
    try:
        async with sessions() as session:
            chunk_ids = tuple(
                await session.scalars(
                    select(RetrievalChunkRecord.id)
                    .where(RetrievalChunkRecord.projection_id == projection_uuid)
                    .order_by(RetrievalChunkRecord.id)
                )
            )
            evidence_unit_ids = tuple(
                await session.scalars(
                    select(EvidenceUnitRecord.id)
                    .where(EvidenceUnitRecord.projection_id == projection_uuid)
                    .order_by(EvidenceUnitRecord.id)
                )
            )
            element_ids = tuple(
                await session.scalars(
                    select(StructuralElementRecord.id)
                    .where(StructuralElementRecord.projection_id == projection_uuid)
                    .order_by(StructuralElementRecord.id)
                )
            )
        assert chunk_ids and evidence_unit_ids and element_ids
        return _private_leak_values(
            workspace_id=workspace_id,
            document_id=document_id,
            asset_version_id=asset_version_id,
            projection_id=projection_id,
            chunk_ids=chunk_ids,
            evidence_unit_ids=evidence_unit_ids,
            element_ids=element_ids,
            title=title,
            marker=marker,
        )
    finally:
        await engine.dispose()


def _expected_keyword_highlights(
    ground_truth: Mapping[str, object],
    terms: Sequence[str],
) -> list[dict[str, object]]:
    text_value = str(ground_truth["text"])
    start_offset = int(ground_truth["char_start"])
    page = ground_truth["page"]
    has_pdf_bbox = ground_truth["bbox"] is not None
    highlights: list[dict[str, object]] = []
    for term in terms:
        relative_start = text_value.index(term)
        highlights.append(
            {
                "kind": "keyword",
                "evidence_unit_id": str(ground_truth["evidence_unit_id"]),
                "text": term,
                "char_start": start_offset + relative_start,
                "char_end": start_offset + relative_start + len(term),
                "page": page,
                "bbox": None,
                "warnings": ["pdf_keyword_bbox_unavailable"] if has_pdf_bbox else [],
            }
        )
    return sorted(
        highlights,
        key=lambda item: (int(item["char_start"]), int(item["char_end"]), str(item["text"])),
    )


def _expected_semantic_highlight(
    ground_truth: Mapping[str, object],
) -> list[dict[str, object]]:
    return [
        {
            "kind": "semantic",
            "evidence_unit_id": str(ground_truth["evidence_unit_id"]),
            "text": ground_truth["text"],
            "char_start": ground_truth["char_start"],
            "char_end": ground_truth["char_end"],
            "page": ground_truth["page"],
            "bbox": ground_truth["bbox"],
            "warnings": [],
        }
    ]


def _assert_normalized_viewer(
    payload: Mapping[str, object],
    *,
    ground_truth: Mapping[str, object],
) -> None:
    assert payload["document_id"] == ground_truth["document_id"]
    assert payload["asset_version_id"] == ground_truth["asset_version_id"]
    assert payload["asset_version_number"] == ground_truth["asset_version_number"]
    assert payload["workspace_id"] == ground_truth["workspace_id"]
    assert payload["folder_id"] == ground_truth["folder_id"]
    assert payload["projection_id"] == ground_truth["projection_id"]
    assert payload["title"] == ground_truth["title"]
    assert payload["media_type"] == ground_truth["media_type"]
    elements = payload["elements"]
    assert isinstance(elements, list)
    expected = next(
        item for item in elements if item["id"] == ground_truth["element_id"]
    )
    assert expected["text"] == ground_truth["element_text"]
    assert expected["section_path"] == ground_truth["element_section_path"]
    assert expected["location"] == {
        "element_id": ground_truth["element_id"],
        "page": ground_truth["page"],
        "char_start": ground_truth["char_start"],
        "char_end": ground_truth["char_end"],
        "bbox": ground_truth["bbox"],
    }


async def _wait_for_ready_projections(
    asset_version_ids: list[object], indexing_profile_id: object
) -> dict[str, str]:
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    expected = {UUID(str(item)) for item in asset_version_ids}
    latest: list[tuple[object, ...]] = []
    try:
        for _attempt in range(360):
            async with sessions() as session:
                latest = [
                    tuple(item)
                    for item in (
                        await session.execute(
                            select(
                                RagProjectionRecord.asset_version_id,
                                RagProjectionRecord.id,
                                RagIngestionJobRecord.job_id,
                                RagProjectionRecord.status,
                                JobRecord.status,
                                JobRecord.stage,
                                JobRecord.error_code,
                            )
                            .join(
                                RagIngestionJobRecord,
                                RagIngestionJobRecord.projection_id
                                == RagProjectionRecord.id,
                            )
                            .join(
                                JobRecord,
                                JobRecord.id == RagIngestionJobRecord.job_id,
                            )
                            .where(
                                RagProjectionRecord.asset_version_id.in_(expected),
                                RagProjectionRecord.indexing_profile_id
                                == UUID(str(indexing_profile_id)),
                            )
                            .order_by(RagProjectionRecord.asset_version_id)
                        )
                    ).all()
                ]
            if {item[0] for item in latest} == expected and all(
                str(item[3]) == "ready" and str(item[4]) == "succeeded"
                for item in latest
            ):
                return {str(item[0]): str(item[1]) for item in latest}
            if any(str(item[3]) == "failed" or str(item[4]) == "failed" for item in latest):
                break
            await sleep(1)
        pytest.fail(
            "RAG projections did not become READY: "
            f"{_projection_diagnostics(latest)}"
        )
    finally:
        await engine.dispose()


def _search_payload(
    *,
    query: str,
    configuration_id: object,
    workspace_ids: list[object],
    experimental: bool = True,
) -> dict[str, object]:
    return {
        "query": query,
        "configuration_id": str(configuration_id),
        "workspace_ids": [str(item) for item in workspace_ids],
        "folder_ids": [],
        "top_k": 10,
        "experimental": experimental,
    }


async def _search(
    client: AsyncClient,
    *,
    query: str,
    configuration_id: object,
    workspace_ids: list[object],
    experimental: bool = True,
) -> tuple[int, dict[str, object]]:
    response = await client.post(
        "/api/v1/rag/search",
        json=_search_payload(
            query=query,
            configuration_id=configuration_id,
            workspace_ids=workspace_ids,
            experimental=experimental,
        ),
    )
    return response.status_code, response.json()


def _expected_snapshot_pairs(
    expected_documents: Mapping[object, object],
) -> set[tuple[UUID, UUID]]:
    pairs = {
        (UUID(str(document_id)), UUID(str(asset_version_id)))
        for document_id, asset_version_id in expected_documents.items()
    }
    assert pairs
    assert len(pairs) == len(expected_documents)
    assert len({asset_version_id for _, asset_version_id in pairs}) == len(pairs)
    return pairs


async def _evaluation_fixture(
    *,
    query: str,
    ground_truth: Mapping[str, object],
    company_workspace_id: object,
    personal_workspace_id: object,
    expected_documents: Mapping[object, object],
) -> dict[str, object]:
    expected_snapshot_pairs = _expected_snapshot_pairs(expected_documents)
    expected_asset_version_ids = {
        asset_version_id for _, asset_version_id in expected_snapshot_pairs
    }
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session:
            snapshot_rows = (
                await session.execute(
                    select(
                        DocumentRecord.id,
                        AssetVersionRecord.id,
                        AssetVersionRecord.sha256,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.document_id == DocumentRecord.id,
                    )
                    .where(DocumentRecord.active_version_id == AssetVersionRecord.id)
                    .where(AssetVersionRecord.id.in_(expected_asset_version_ids))
                    .order_by(DocumentRecord.id)
                )
            ).all()
            company_evidence = set(
                await session.scalars(
                    select(EvidenceUnitRecord.id)
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.id == EvidenceUnitRecord.projection_id,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                    )
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == AssetVersionRecord.document_id,
                    )
                    .where(DocumentRecord.workspace_id == UUID(str(company_workspace_id)))
                )
            )
            private_evidence = set(
                await session.scalars(
                    select(EvidenceUnitRecord.id)
                    .join(
                        RagProjectionRecord,
                        RagProjectionRecord.id == EvidenceUnitRecord.projection_id,
                    )
                    .join(
                        AssetVersionRecord,
                        AssetVersionRecord.id == RagProjectionRecord.asset_version_id,
                    )
                    .join(
                        DocumentRecord,
                        DocumentRecord.id == AssetVersionRecord.document_id,
                    )
                    .where(DocumentRecord.workspace_id == UUID(str(personal_workspace_id)))
                )
            )
    finally:
        await engine.dispose()
    assert {
        (document_id, asset_version_id)
        for document_id, asset_version_id, _ in snapshot_rows
    } == expected_snapshot_pairs
    assert company_evidence
    assert private_evidence
    return {
        "schema_version": 1,
        "id": str(uuid4()),
        "name": "Task 14 live public synthetic evaluation",
        "version": 1,
        "document_snapshot": [
            {
                "document_id": str(document_id),
                "asset_version_id": str(asset_version_id),
                "sha256": digest,
                "active": True,
            }
            for document_id, asset_version_id, digest in snapshot_rows
        ],
        "cases": [
            _evaluation_case(
                query=query,
                ground_truth=ground_truth,
                company_workspace_id=company_workspace_id,
                authorized_source_ids=tuple(company_evidence),
                forbidden_source_ids=tuple(private_evidence),
                as_of=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            )
        ],
    }


async def _wait_for_evaluation(
    client: AsyncClient, run_id: object
) -> dict[str, object]:
    latest: dict[str, object] | None = None
    for _attempt in range(360):
        response = await client.get(f"/api/v1/rag/evaluation-runs/{run_id}")
        assert response.status_code == 200
        latest = response.json()
        if latest["status"] in {"completed", "failed"}:
            return latest
        await sleep(1)
    pytest.fail(
        "Evaluation did not finish: "
        f"run_id={run_id}, status={latest and latest.get('status')}"
    )


async def _prepare_known_owner(
    *,
    bootstrap: Callable[[str, str], Awaitable[None]] = bootstrap_owner,
) -> None:
    with patch(
        "ai_workshop.platform.identity.cli.getpass",
        side_effect=[TEST_PASSWORD, TEST_PASSWORD],
    ):
        try:
            await bootstrap("Task 14 Owner", OWNER_EMAIL)
        except SystemExit as exc:
            if str(exc) != "An owner already exists.":
                raise


@actual_stack
@pytest.mark.asyncio
async def test_first_rag_search_vertical_slice_on_actual_stack(
    prepared_rag_stack: None,
) -> None:
    del prepared_rag_stack
    await _prepare_known_owner()

    exact_sentence = "COMPANY-RISK-CODE-AX17 requires daily compliance review."
    semantic_sentence = (
        "Investors must submit redemption notice five business days before payout."
    )
    private_sentence = (
        "PRIVATE-OWNER-MARKER-Q91 is a synthetic personal research note."
    )
    pdf_sentence = "PUBLIC-LIQUIDITY-WINDOW-PDF is 14 calendar days."
    markdown = (
        f"# Public Risk Policy\n\n{exact_sentence}\n\n{semantic_sentence}\n"
    ).encode()
    private_text = (
        f"{private_sentence}\n"
        "It must never appear in company-member search results.\n"
    ).encode()
    pdf = _text_pdf()

    async with _remote_client() as owner:
        await _login(owner, OWNER_EMAIL)
        company = await _create_workspace(
            owner, name="Task 14 Company Knowledge", kind="company"
        )
        personal = await _get_or_create_personal_workspace(
            owner, name="Task 14 Owner Notes"
        )
        member_id = await _seed_member_and_membership(company["id"])
        del member_id
        markdown_document, markdown_version = await _upload(
            owner,
            company["id"],
            name="public-risk-policy.md",
            media_type="text/markdown",
            content=markdown,
        )
        private_document, private_version = await _upload(
            owner,
            personal["id"],
            name="private-owner-note.txt",
            media_type="text/plain",
            content=private_text,
        )
        await _verify_stored_object(markdown_version["id"], markdown)
        await _verify_stored_object(private_version["id"], private_text)

        indexing, _bm25, hybrid = await _register_rag_components(owner)
        saved_response = await owner.post(
            "/api/v1/rag/configurations",
            json={
                "name": "Task 14 E5 Hybrid",
                "indexing_profile_id": indexing["id"],
                "retrieval_profile_id": hybrid["id"],
                "generation_profile_id": None,
                "answer_policy": {
                    "min_semantic_score": 0.0,
                    "min_keyword_coverage": 0.5,
                    "require_complete_provenance": True,
                    "conflict_mode": "separate_sources",
                },
                "workspace_ids": [company["id"], personal["id"]],
            },
        )
        assert saved_response.status_code == 201
        saved = saved_response.json()
        projections = await _prepare_ready_projections(
            [markdown_version["id"], private_version["id"]], indexing["id"]
        )
        markdown_exact_truth = await _load_ground_truth(
            document_id=markdown_document["id"],
            asset_version_id=markdown_version["id"],
            projection_id=projections[str(markdown_version["id"])],
            expected_text=exact_sentence,
        )
        markdown_semantic_truth = await _load_ground_truth(
            document_id=markdown_document["id"],
            asset_version_id=markdown_version["id"],
            projection_id=projections[str(markdown_version["id"])],
            expected_text=semantic_sentence,
        )
        private_values = await _load_private_leak_values(
            workspace_id=personal["id"],
            document_id=private_document["id"],
            asset_version_id=private_version["id"],
            projection_id=projections[str(private_version["id"])],
            title="private-owner-note.txt",
            marker="PRIVATE-OWNER-MARKER-Q91",
        )

        exact_query = "COMPANY-RISK-CODE-AX17"
        status, exact = await _search(
            owner,
            query=exact_query,
            configuration_id=saved["id"],
            workspace_ids=[company["id"]],
        )
        assert status == 200
        assert exact["status"] == "supported"
        assert isinstance(exact["answer"], dict)
        _assert_grounded_answer(
            exact["answer"],
            ground_truth=markdown_exact_truth,
            expected_excerpt=exact_sentence,
            expected_highlights=_expected_keyword_highlights(
                markdown_exact_truth,
                ("COMPANY", "RISK", "CODE", "AX17"),
            ),
        )
        assert exact["configuration_version"]["version_id"] == saved["version_id"]
        assert exact["experimental"] is True

        semantic_status, semantic = await _search(
            owner,
            query="How early is advance withdrawal notification required?",
            configuration_id=saved["id"],
            workspace_ids=[company["id"]],
        )
        assert semantic_status == 200
        assert semantic["status"] == "supported"
        assert isinstance(semantic["answer"], dict)
        _assert_grounded_answer(
            semantic["answer"],
            ground_truth=markdown_semantic_truth,
            expected_excerpt=semantic_sentence,
            expected_highlights=_expected_semantic_highlight(
                markdown_semantic_truth
            ),
        )
        assert "five business days" in semantic["answer"]["excerpt"]

        markdown_view = await owner.get(
            f"/api/v1/rag/sources/{markdown_version['id']}/normalized-text",
            params={"projection_id": projections[str(markdown_version["id"])]},
        )
        assert markdown_view.status_code == 200
        _assert_normalized_viewer(
            markdown_view.json(),
            ground_truth=markdown_exact_truth,
        )

        pdf_document, pdf_version = await _upload(
            owner,
            company["id"],
            name="public-liquidity-window.pdf",
            media_type="application/pdf",
            content=pdf,
        )
        await _verify_stored_object(pdf_version["id"], pdf)
        new_projection = await _prepare_ready_projections(
            [pdf_version["id"]], indexing["id"]
        )
        projections.update(new_projection)
        pdf_truth = await _load_ground_truth(
            document_id=pdf_document["id"],
            asset_version_id=pdf_version["id"],
            projection_id=projections[str(pdf_version["id"])],
            expected_text=pdf_sentence,
        )
        new_status, new_result = await _search(
            owner,
            query="PUBLIC-LIQUIDITY-WINDOW-PDF",
            configuration_id=saved["id"],
            workspace_ids=[company["id"]],
        )
        assert new_status == 200
        assert new_result["status"] == "supported"
        assert isinstance(new_result["answer"], dict)
        _assert_grounded_answer(
            new_result["answer"],
            ground_truth=pdf_truth,
            expected_excerpt=pdf_sentence,
            expected_highlights=_expected_keyword_highlights(
                pdf_truth,
                ("PUBLIC", "LIQUIDITY", "WINDOW", "PDF"),
            ),
        )
        assert "14 calendar days" in new_result["answer"]["excerpt"]

        existing_status, existing = await _search(
            owner,
            query=exact_query,
            configuration_id=saved["id"],
            workspace_ids=[company["id"]],
        )
        assert existing_status == 200
        assert existing["status"] == "supported"
        assert isinstance(existing["answer"], dict)
        _assert_grounded_answer(
            existing["answer"],
            ground_truth=markdown_exact_truth,
            expected_excerpt=exact_sentence,
            expected_highlights=_expected_keyword_highlights(
                markdown_exact_truth,
                ("COMPANY", "RISK", "CODE", "AX17"),
            ),
        )
        assert existing["related_sources"]
        assert all(
            item["workspace_id"] == company["id"]
            and item["document_id"] == pdf_document["id"]
            and item["asset_version_id"] == pdf_version["id"]
            and item["asset_version_number"] == pdf_truth["asset_version_number"]
            and item["projection_id"] == pdf_truth["projection_id"]
            and item["chunk_id"] == pdf_truth["chunk_id"]
            and item["title"] == pdf_truth["title"]
            and item["media_type"] == pdf_truth["media_type"]
            for item in existing["related_sources"]
        )

        pdf_normalized = await owner.get(
            f"/api/v1/rag/sources/{pdf_version['id']}/normalized-text",
            params={"projection_id": projections[str(pdf_version["id"])]},
        )
        assert pdf_normalized.status_code == 200
        _assert_normalized_viewer(
            pdf_normalized.json(),
            ground_truth=pdf_truth,
        )

        pdf_page = await owner.get(
            f"/api/v1/rag/sources/{pdf_version['id']}/pdf/pages/1",
            params={"projection_id": projections[str(pdf_version["id"])]},
        )
        assert pdf_page.status_code == 200
        assert pdf_page.headers["content-type"].startswith("image/png")
        assert pdf_page.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert pdf_page.headers["x-ai-workshop-asset-version"] == pdf_version["id"]
        assert pdf_truth["page"] == 1
        assert pdf_truth["bbox"] is not None

        fixture = await _evaluation_fixture(
            query=exact_query,
            ground_truth=markdown_exact_truth,
            company_workspace_id=company["id"],
            personal_workspace_id=personal["id"],
            expected_documents={
                markdown_document["id"]: markdown_version["id"],
                private_document["id"]: private_version["id"],
                pdf_document["id"]: pdf_version["id"],
            },
        )
        run_response = await owner.post(
            "/api/v1/rag/evaluation-runs",
            json={
                "dataset_fixture": fixture,
                "evaluation_policy_version_id": None,
                "configuration_version_ids": [saved["version_id"]],
                "metric_definition_version": 1,
                "retrieval_k": 10,
                "repetition_count": 2,
            },
        )
        assert run_response.status_code == 202
        _dispatch_pending_evaluation()
        evaluation = await _wait_for_evaluation(owner, run_response.json()["id"])
        assert evaluation["status"] == "completed"
        assert [item["configuration_version_id"] for item in evaluation["candidates"]] == [
            str(BM25_BASELINE_CONFIGURATION_VERSION_ID),
            saved["version_id"],
        ]
        assert all(item["status"] == "completed" for item in evaluation["candidates"])
        candidate_ground_truth = await _load_evaluation_candidate_ground_truth(
            run_id=evaluation["id"],
            expected_configuration_version_ids=(
                BM25_BASELINE_CONFIGURATION_VERSION_ID,
                saved["version_id"],
            ),
        )
        assert all(
            candidate_ground_truth[item["configuration_version_id"]]
            == {
                "status": "completed",
                "failures": [],
                "case_result_count": 1,
            }
            for item in evaluation["candidates"]
        )
        assert all(item["metrics"]["access_leaks"] == 0 for item in evaluation["candidates"])
        assert all(item["metrics"]["reproducibility"] == 1.0 for item in evaluation["candidates"])

        promotion = await owner.post(f"/api/v1/rag/configurations/{saved['id']}/default")
        assert promotion.status_code == 409
        assert promotion.json()["error"]["code"] == "evaluation_policy_required"

    async with _remote_client() as member:
        await _login(member, MEMBER_EMAIL)
        visible = await member.get("/api/v1/rag/configurations")
        assert visible.status_code == 200
        assert [item["id"] for item in visible.json()] == [
            str(BM25_BASELINE_CONFIGURATION_ID)
        ]
        hidden_configuration = await member.get(
            f"/api/v1/rag/configurations/{saved['id']}"
        )
        assert hidden_configuration.status_code == 404

        company_status, company_result = await _search(
            member,
            query=exact_query,
            configuration_id=BM25_BASELINE_CONFIGURATION_ID,
            workspace_ids=[company["id"]],
        )
        assert company_status == 200
        assert company_result["status"] == "supported"
        assert isinstance(company_result["answer"], dict)
        _assert_grounded_answer(
            company_result["answer"],
            ground_truth=markdown_exact_truth,
            expected_excerpt=exact_sentence,
            expected_highlights=_expected_keyword_highlights(
                markdown_exact_truth,
                ("COMPANY", "RISK", "CODE", "AX17"),
            ),
        )

        insufficient_status, insufficient = await _search(
            member,
            query=INSUFFICIENT_QUERY,
            configuration_id=BM25_BASELINE_CONFIGURATION_ID,
            workspace_ids=[company["id"]],
        )
        assert insufficient_status == 200
        assert insufficient["status"] == "insufficient_evidence"
        assert insufficient["answer"] is None
        assert insufficient["conflict_state"] == "none"
        assert insufficient["conflicts"] == []
        assert insufficient["related_sources"] == []
        assert all(value not in repr(insufficient) for value in private_values)

        leak_status, leak_result = await _search(
            member,
            query="PRIVATE-OWNER-MARKER-Q91",
            configuration_id=BM25_BASELINE_CONFIGURATION_ID,
            workspace_ids=[company["id"]],
        )
        assert leak_status == 200
        assert leak_result["status"] == "insufficient_evidence"
        assert leak_result["answer"] is None
        assert leak_result["conflicts"] == []
        assert leak_result["related_sources"] == []
        leaked = repr(leak_result)
        assert all(private_value not in leaked for private_value in private_values)

        private_status, _private_result = await _search(
            member,
            query="PRIVATE-OWNER-MARKER-Q91",
            configuration_id=BM25_BASELINE_CONFIGURATION_ID,
            workspace_ids=[personal["id"]],
        )
        assert private_status == 404
        private_viewer = await member.get(
            f"/api/v1/rag/sources/{private_version['id']}/normalized-text",
            params={"projection_id": projections[str(private_version["id"])]},
        )
        assert private_viewer.status_code == 404
        owner_run = await member.get(
            f"/api/v1/rag/evaluation-runs/{evaluation['id']}"
        )
        assert owner_run.status_code == 404
        member_runs = await member.get("/api/v1/rag/evaluation-runs")
        assert member_runs.status_code == 200
        assert member_runs.json() == []
        member_visible_payloads = repr(
            (
                visible.json(),
                company_result,
                insufficient,
                leak_result,
                member_runs.json(),
            )
        )
        assert all(value not in member_visible_payloads for value in private_values)
