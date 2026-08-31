from asyncio import sleep
from collections.abc import AsyncIterator, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from os import environ
from unittest.mock import patch
from uuid import UUID, uuid4

import pymupdf
import pytest
from elasticsearch import AsyncElasticsearch
from httpx import AsyncClient
from sqlalchemy import select, text

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
)
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import ElasticsearchSearchIndex
from ai_workshop.labs.rag.indexing.service import IndexingService
from ai_workshop.labs.rag.ingestion.models import RagIngestionJobRecord
from ai_workshop.platform.assets.models import AssetVersionRecord, DocumentRecord
from ai_workshop.platform.identity.cli import bootstrap_owner
from ai_workshop.platform.identity.domain import User
from ai_workshop.platform.identity.repository import SqlAlchemyUserRepository
from ai_workshop.platform.identity.service import Argon2PasswordHasher
from ai_workshop.platform.jobs.models import JobRecord
from ai_workshop.platform.workspaces.domain import MembershipRole
from ai_workshop.platform.workspaces.models import WorkspaceMembershipRecord
from ai_workshop.shared.db import create_engine, create_session_factory

pytestmark = pytest.mark.skipif(
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
RAG_TRUNCATE_SQL = """
TRUNCATE TABLE rag_model_definitions, users RESTART IDENTITY CASCADE
"""


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


@pytest.mark.asyncio
async def test_ready_documents_remain_searchable_after_another_projection_activates() -> None:
    """A profile-wide active search view must retain every READY document."""
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
        await client.indices.delete(index=list(concrete_indices), ignore_unavailable=True)
        await client.close()


@pytest.fixture
async def isolated_rag_stack() -> AsyncIterator[None]:
    settings = get_settings()
    if settings.environment != "test":
        pytest.fail("RAG E2E requires AI_WORKSHOP_ENVIRONMENT=test.")
    if not environ.get("AI_WORKSHOP_E2E_BASE_URL"):
        pytest.fail("RAG E2E requires the remote Compose API base URL.")
    engine = create_engine(settings)
    elasticsearch = create_elasticsearch(settings)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(RAG_TRUNCATE_SQL))
        await _delete_isolated_indices(elasticsearch)
        yield
    finally:
        async with engine.begin() as connection:
            await connection.execute(text(RAG_TRUNCATE_SQL))
        await _delete_isolated_indices(elasticsearch)
        await elasticsearch.close()
        await engine.dispose()


async def _delete_isolated_indices(elasticsearch: AsyncElasticsearch) -> None:
    settings = get_settings()
    indices = elasticsearch.indices
    matches = await indices.get(
        index=f"{settings.elasticsearch_index_prefix}-*",
        allow_no_indices=True,
        expand_wildcards="all",
    )
    exact_names = sorted(matches)
    if exact_names:
        await indices.delete(index=exact_names, ignore_unavailable=True)


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
    model_response = await client.post(
        "/api/v1/rag/models",
        json={
            "kind": "embedding",
            "name": "task14-multilingual-e5-base",
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
        },
    )
    assert model_response.status_code == 201
    model = model_response.json()
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


async def _evaluation_fixture(
    *,
    query: str,
    answer: dict[str, object],
    company_workspace_id: object,
    personal_workspace_id: object,
) -> dict[str, object]:
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
    source = answer["source"]
    assert isinstance(source, dict)
    highlight = answer["highlights"][0]
    assert isinstance(highlight, dict)
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
            {
                "id": str(uuid4()),
                "kind": "exact_code",
                "query": query,
                "query_sha256": sha256(query.encode()).hexdigest(),
                "permission_scenario": {
                    "name": "task14-company-owner",
                    "actor": "caller",
                    "workspace_ids": [str(company_workspace_id)],
                    "folder_ids": [],
                    "authorized_source_ids": sorted(str(item) for item in company_evidence),
                    "forbidden_source_ids": sorted(str(item) for item in private_evidence),
                    "as_of": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                },
                "expected": {
                    "answer_status": "supported",
                    "evidence_unit_ids": [source["evidence_unit_id"]],
                    "highlight": {
                        "surface": "answer",
                        "document_id": source["document_id"],
                        "asset_version_id": source["asset_version_id"],
                        "evidence_unit_id": source["evidence_unit_id"],
                        "page": highlight["page"],
                        "kind": highlight["kind"],
                        "spans": [
                            [highlight["char_start"], highlight["char_end"]]
                        ]
                        if highlight["bbox"] is None
                        else [],
                        "bboxes": [highlight["bbox"]]
                        if highlight["bbox"] is not None
                        else [],
                    },
                },
            }
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


@pytest.mark.asyncio
async def test_first_rag_search_vertical_slice_on_actual_stack(
    isolated_rag_stack: None,
) -> None:
    del isolated_rag_stack
    with patch(
        "ai_workshop.platform.identity.cli.getpass",
        side_effect=[TEST_PASSWORD, TEST_PASSWORD],
    ):
        await bootstrap_owner("Task 14 Owner", OWNER_EMAIL)

    markdown = (
        b"# Public Risk Policy\n\n"
        b"COMPANY-RISK-CODE-AX17 requires daily compliance review.\n\n"
        b"Investors must submit redemption notice five business days before payout.\n"
    )
    private_text = (
        b"PRIVATE-OWNER-MARKER-Q91 is a synthetic personal research note.\n"
        b"It must never appear in company-member search results.\n"
    )
    pdf = _text_pdf()

    async with _remote_client() as owner:
        await _login(owner, OWNER_EMAIL)
        company = await _create_workspace(
            owner, name="Task 14 Company Knowledge", kind="company"
        )
        personal = await _create_workspace(
            owner, name="Task 14 Owner Notes", kind="personal"
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
        projections = await _wait_for_ready_projections(
            [markdown_version["id"], private_version["id"]], indexing["id"]
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
        assert exact["answer"]["source"]["document_id"] == markdown_document["id"]
        assert exact["answer"]["highlights"][0]["kind"] == "keyword"
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
        assert semantic["answer"]["source"]["document_id"] == markdown_document["id"]
        assert semantic["answer"]["highlights"][0]["kind"] == "semantic"

        markdown_view = await owner.get(
            f"/api/v1/rag/sources/{markdown_version['id']}/normalized-text",
            params={"projection_id": projections[str(markdown_version["id"])]},
        )
        assert markdown_view.status_code == 200
        assert markdown_view.json()["asset_version_id"] == markdown_version["id"]
        assert markdown_view.json()["elements"]

        pdf_document, pdf_version = await _upload(
            owner,
            company["id"],
            name="public-liquidity-window.pdf",
            media_type="application/pdf",
            content=pdf,
        )
        await _verify_stored_object(pdf_version["id"], pdf)
        new_projection = await _wait_for_ready_projections(
            [pdf_version["id"]], indexing["id"]
        )
        projections.update(new_projection)
        new_status, new_result = await _search(
            owner,
            query="PUBLIC-LIQUIDITY-WINDOW-PDF",
            configuration_id=saved["id"],
            workspace_ids=[company["id"]],
        )
        assert new_status == 200
        assert new_result["status"] == "supported"
        assert new_result["answer"]["source"]["document_id"] == pdf_document["id"]

        existing_status, existing = await _search(
            owner,
            query=exact_query,
            configuration_id=saved["id"],
            workspace_ids=[company["id"]],
        )
        assert existing_status == 200
        assert existing["answer"]["source"]["document_id"] == markdown_document["id"]

        pdf_page = await owner.get(
            f"/api/v1/rag/sources/{pdf_version['id']}/pdf/pages/1",
            params={"projection_id": projections[str(pdf_version["id"])]},
        )
        assert pdf_page.status_code == 200
        assert pdf_page.headers["content-type"].startswith("image/png")
        assert pdf_page.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert pdf_page.headers["x-ai-workshop-asset-version"] == pdf_version["id"]

        fixture = await _evaluation_fixture(
            query=exact_query,
            answer=exact["answer"],
            company_workspace_id=company["id"],
            personal_workspace_id=personal["id"],
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
        evaluation = await _wait_for_evaluation(owner, run_response.json()["id"])
        assert evaluation["status"] == "completed"
        assert [item["configuration_version_id"] for item in evaluation["candidates"]] == [
            str(BM25_BASELINE_CONFIGURATION_VERSION_ID),
            saved["version_id"],
        ]
        assert all(item["status"] == "completed" for item in evaluation["candidates"])
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
        assert company_result["answer"]["source"]["document_id"] == markdown_document["id"]

        leak_status, leak_result = await _search(
            member,
            query="PRIVATE-OWNER-MARKER-Q91",
            configuration_id=BM25_BASELINE_CONFIGURATION_ID,
            workspace_ids=[company["id"]],
        )
        assert leak_status == 200
        leaked = repr(leak_result)
        for private_value in (
            personal["id"],
            private_document["id"],
            private_version["id"],
            projections[str(private_version["id"])],
            "PRIVATE-OWNER-MARKER-Q91",
            "private-owner-note.txt",
        ):
            assert str(private_value) not in leaked

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
