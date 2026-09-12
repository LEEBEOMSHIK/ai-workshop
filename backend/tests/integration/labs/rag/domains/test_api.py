from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from ai_workshop.labs.rag.domains.api import (
    DomainSearchExecutor,
    get_domain_search_executor,
    get_domain_service,
)
from ai_workshop.labs.rag.domains.schemas import DomainSearchRequest
from ai_workshop.labs.rag.domains.service import (
    AdminDomainConnectionVersion,
    Domain,
    DomainConnectionVersion,
    DomainSearchContext,
    DomainView,
    DomainWorkspaceOption,
)
from ai_workshop.main import create_app
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.platform.workspaces.domain import WorkspaceKind
from ai_workshop.shared.errors import AppError

OWNER_ID = UUID("10000000-0000-0000-0000-000000000001")
MEMBER_ID = UUID("10000000-0000-0000-0000-000000000002")
DOMAIN_ID = UUID("20000000-0000-0000-0000-000000000001")
CONNECTION_ID = UUID("20000000-0000-0000-0000-000000000002")
CONFIGURATION_VERSION_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("40000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("50000000-0000-0000-0000-000000000001")
ASSET_VERSION_ID = UUID("50000000-0000-0000-0000-000000000002")
PROJECTION_ID = UUID("50000000-0000-0000-0000-000000000003")
INDEX_BUILD_ID = UUID("50000000-0000-0000-0000-000000000004")
SCOPE_FINGERPRINT = "a" * 64


def _user(role: UserRole) -> User:
    user_id = OWNER_ID if role is UserRole.OWNER else MEMBER_ID
    return User(
        id=user_id,
        display_name=role.value,
        email=f"{role.value}@example.test",
        normalized_email=f"{role.value}@example.test",
        password_hash="hash",
        role=role,
    )


def _view() -> DomainView:
    domain = Domain(
        id=DOMAIN_ID,
        slug="fund-management",
        display_name="자산운용",
        description="운용 지식",
        active_connection_version_id=CONNECTION_ID,
        created_by=OWNER_ID,
    )
    connection = DomainConnectionVersion(
        id=CONNECTION_ID,
        domain_id=DOMAIN_ID,
        version=3,
        configuration_version_id=CONFIGURATION_VERSION_ID,
        workspace_ids=(WORKSPACE_ID,),
        created_by=OWNER_ID,
    )
    return DomainView(
        domain=domain,
        connection=connection,
        workspace_options=(
            DomainWorkspaceOption(
                WORKSPACE_ID,
                "허용 공간",
                WorkspaceKind.TEAM,
                None,
            ),
        ),
        active=True,
        ready=True,
        search_ready=True,
        answer_ready=True,
        reason_codes=(),
    )


class FakeDomainService:
    def __init__(self) -> None:
        self.view = _view()
        self.created: dict[str, object] | None = None
        self.calls: list[str] = []

    async def list_for_actor(self, actor_id: UUID) -> tuple[DomainView, ...]:
        assert actor_id in {OWNER_ID, MEMBER_ID}
        self.calls.append("actor")
        return (self.view,)

    async def list_for_owner(self, actor_id: UUID) -> tuple[DomainView, ...]:
        assert actor_id == OWNER_ID
        self.calls.append("owner")
        return (self.view,)

    async def detail_for_actor(self, slug: str, actor_id: UUID) -> DomainView:
        assert (slug, actor_id) == ("fund-management", MEMBER_ID)
        return self.view

    async def create_domain(self, **values: object) -> Domain:
        self.created = values
        return replace(self.view.domain, active_connection_version_id=None)

    async def update_domain(self, **values: object) -> Domain:
        return replace(
            self.view.domain,
            display_name=str(values["display_name"]),
            description=str(values["description"]),
        )

    async def create_connection(self, **values: object) -> DomainConnectionVersion:
        self.created = values
        assert self.view.connection is not None
        return self.view.connection

    async def activate_connection(self, **values: object) -> Domain:
        self.created = values
        return self.view.domain

    async def deactivate(self, **values: object) -> Domain:
        self.created = values
        return replace(self.view.domain, active_connection_version_id=None)

    async def connections_for_owner(
        self, domain_id: UUID
    ) -> tuple[AdminDomainConnectionVersion, ...]:
        assert domain_id == DOMAIN_ID
        assert self.view.connection is not None
        return (
            AdminDomainConnectionVersion(
                connection=self.view.connection,
                configuration_name="검증된 구성",
                configuration_version=7,
            ),
        )


class FakeDomainSearchExecutor:
    def __init__(self) -> None:
        self.call: tuple[str, UUID, DomainSearchRequest] | None = None

    async def execute(
        self,
        *,
        slug: str,
        actor_id: UUID,
        request: DomainSearchRequest,
    ) -> dict[str, object]:
        self.call = (slug, actor_id, request)
        return {
            "status": "insufficient_evidence",
            "answer": None,
            "conflict_state": "none",
            "conflicts": [],
            "warnings": [],
            "related_sources": [],
            "configuration_version": {
                "configuration_id": uuid4(),
                "version_id": CONFIGURATION_VERSION_ID,
                "version": 1,
            },
            "experimental": False,
            "resolved_query": request.query,
            "selected_scope": (
                {
                    "identities": [
                        {
                            "document_id": DOCUMENT_ID,
                            "asset_version_id": ASSET_VERSION_ID,
                            "projection_id": PROJECTION_ID,
                            "index_build_id": INDEX_BUILD_ID,
                        }
                    ],
                    "fingerprint": SCOPE_FINGERPRINT,
                }
                if request.document_ids == [DOCUMENT_ID]
                else None
            ),
            "generation": {
                "status": "insufficient_evidence",
                "text": None,
                "citations": [],
                "reason_codes": [],
                "turn_id": None,
                "validation_token": None,
                "execution": None,
            },
            "domain_context": {
                "domain_id": DOMAIN_ID,
                "connection_version_id": request.connection_version_id,
                "workspace_ids": request.workspace_ids,
                "folder_ids": request.folder_ids,
            },
        }


def _client(
    role: UserRole,
    service: FakeDomainService,
    executor: FakeDomainSearchExecutor | None = None,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: _user(role)
    app.dependency_overrides[get_domain_service] = lambda: service
    if executor is not None:
        app.dependency_overrides[get_domain_search_executor] = lambda: executor
    return TestClient(app)


def test_authenticated_member_lists_only_server_resolved_workspace_options() -> None:
    with _client(UserRole.MEMBER, FakeDomainService()) as client:
        response = client.get("/api/v1/rag/domains")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(DOMAIN_ID),
            "slug": "fund-management",
            "display_name": "자산운용",
            "description": "운용 지식",
            "active": True,
            "ready": True,
            "connection_version": {"id": str(CONNECTION_ID), "version": 3},
            "readiness": {
                "search_ready": True,
                "answer_ready": True,
                "service_ready": True,
                "reason_codes": [],
            },
            "workspace_options": [
                {
                    "id": str(WORKSPACE_ID),
                    "name": "허용 공간",
                    "kind": "team",
                    "expires_at": None,
                }
            ],
            "generation_execution_preview": None,
        }
    ]


def test_owner_list_domains_uses_owner_scoped_domains() -> None:
    service = FakeDomainService()
    with _client(UserRole.OWNER, service) as client:
        response = client.get("/api/v1/rag/domains")

    assert response.status_code == 200
    assert service.calls[-1] == "owner"
    assert response.json() == [
        {
            "id": str(DOMAIN_ID),
            "slug": "fund-management",
            "display_name": "자산운용",
            "description": "운용 지식",
            "active": True,
            "ready": True,
            "connection_version": {"id": str(CONNECTION_ID), "version": 3},
            "readiness": {
                "search_ready": True,
                "answer_ready": True,
                "service_ready": True,
                "reason_codes": [],
            },
            "workspace_options": [
                {
                    "id": str(WORKSPACE_ID),
                    "name": "허용 공간",
                    "kind": "team",
                    "expires_at": None,
                }
            ],
            "generation_execution_preview": None,
        }
    ]


def test_member_cannot_create_admin_domain() -> None:
    service = FakeDomainService()
    with _client(UserRole.MEMBER, service) as client:
        response = client.post(
            "/api/v1/admin/rag/domains",
            json={
                "slug": "legal",
                "display_name": "법률",
                "description": "법률 지식",
            },
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "owner_required"
    assert service.created is None


def test_anonymous_user_cannot_list_domains() -> None:
    async def anonymous() -> User:
        raise AppError("authentication_required", "Authentication is required.", 401)

    app = create_app()
    app.dependency_overrides[get_current_user] = anonymous
    app.dependency_overrides[get_domain_service] = lambda: FakeDomainService()
    with TestClient(app) as client:
        response = client.get("/api/v1/rag/domains")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"


def test_owner_creates_domain_without_seed_or_implicit_connection() -> None:
    service = FakeDomainService()
    with _client(UserRole.OWNER, service) as client:
        response = client.post(
            "/api/v1/admin/rag/domains",
            json={
                "slug": "fund-management",
                "display_name": "자산운용",
                "description": "운용 지식",
            },
        )

    assert response.status_code == 201
    assert service.created == {
        "actor_id": OWNER_ID,
        "slug": "fund-management",
        "display_name": "자산운용",
        "description": "운용 지식",
    }
    assert response.json()["active_connection_version_id"] is None


def test_owner_can_read_immutable_connection_versions() -> None:
    with _client(UserRole.OWNER, FakeDomainService()) as client:
        response = client.get(
            f"/api/v1/admin/rag/domains/{DOMAIN_ID}/connections"
        )

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(CONNECTION_ID),
            "domain_id": str(DOMAIN_ID),
            "version": 3,
            "configuration_version_id": str(CONFIGURATION_VERSION_ID),
            "configuration_name": "검증된 구성",
            "configuration_version": 7,
            "workspace_ids": [str(WORKSPACE_ID)],
            "created_by": str(OWNER_ID),
            "created_at": None,
        }
    ]


def test_domain_search_keeps_member_actor_and_has_no_configuration_override() -> None:
    service = FakeDomainService()
    executor = FakeDomainSearchExecutor()
    payload = {
        "connection_version_id": str(CONNECTION_ID),
        "query": "환매 기준은?",
        "workspace_ids": [str(WORKSPACE_ID)],
        "folder_ids": [],
        "history": [],
    }
    with _client(UserRole.MEMBER, service, executor) as client:
        response = client.post(
            "/api/v1/rag/domains/fund-management/search",
            json=payload,
        )

    assert response.status_code == 200
    assert executor.call is not None
    assert executor.call[:2] == ("fund-management", MEMBER_ID)
    assert "configuration_id" not in payload
    assert response.json()["domain_context"] == {
        "domain_id": str(DOMAIN_ID),
        "connection_version_id": str(CONNECTION_ID),
        "workspace_ids": [str(WORKSPACE_ID)],
        "folder_ids": [],
    }


def test_domain_search_http_preserves_selected_documents_and_selected_scope() -> None:
    service = FakeDomainService()
    executor = FakeDomainSearchExecutor()
    payload = {
        "connection_version_id": str(CONNECTION_ID),
        "query": "환매 기준은?",
        "workspace_ids": [str(WORKSPACE_ID)],
        "folder_ids": [],
        "document_ids": [str(DOCUMENT_ID)],
        "history": [],
    }
    with _client(UserRole.MEMBER, service, executor) as client:
        response = client.post(
            "/api/v1/rag/domains/fund-management/search",
            json=payload,
        )

    assert response.status_code == 200
    assert executor.call is not None
    assert executor.call[:2] == ("fund-management", MEMBER_ID)
    assert executor.call[2].document_ids == [DOCUMENT_ID]
    assert "configuration_id" not in payload
    assert response.json()["selected_scope"] == {
        "identities": [
            {
                "document_id": str(DOCUMENT_ID),
                "asset_version_id": str(ASSET_VERSION_ID),
                "projection_id": str(PROJECTION_ID),
                "index_build_id": str(INDEX_BUILD_ID),
            }
        ],
        "fingerprint": SCOPE_FINGERPRINT,
    }


async def test_domain_executor_keeps_member_actor_and_full_configuration_policy_scope() -> None:
    private_workspace_id = uuid4()
    context_configuration_id = uuid4()
    selected_document_id = uuid4()
    calls: dict[str, object] = {}

    class Boundary:
        async def resolve_search(self, **values: object) -> DomainSearchContext:
            calls["boundary"] = values
            document_ids = values["document_ids"]
            assert isinstance(document_ids, tuple)
            return DomainSearchContext(
                actor_id=MEMBER_ID,
                domain_id=DOMAIN_ID,
                connection_version_id=CONNECTION_ID,
                configuration_version_id=CONFIGURATION_VERSION_ID,
                configuration_id=context_configuration_id,
                workspace_ids=(WORKSPACE_ID,),
                folder_ids=(),
                document_ids=document_ids,
            )

    configuration = SimpleNamespace(
        configuration_id=uuid4(),
        configuration_version_id=CONFIGURATION_VERSION_ID,
        experimental=True,
        workspace_ids=(WORKSPACE_ID, private_workspace_id),
    )

    class Resolver:
        async def resolve_domain_version(
            self, configuration_version_id: UUID, actor_id: UUID
        ) -> object:
            calls["resolver"] = (configuration_version_id, actor_id)
            return configuration

    class Search:
        async def search_resolved(self, **values: object) -> object:
            calls["search"] = values
            raise AppError("stop_after_boundary", "Synthetic stop.", 409)

    configuration.configuration_id = context_configuration_id
    executor = DomainSearchExecutor(
        Boundary(),  # type: ignore[arg-type]
        Resolver(),  # type: ignore[arg-type]
        Search(),  # type: ignore[arg-type]
    )
    with pytest.raises(AppError) as caught:
        await executor.execute(
            slug="fund-management",
            actor_id=MEMBER_ID,
            request=DomainSearchRequest(
                connection_version_id=CONNECTION_ID,
                query="검색 질문",
                workspace_ids=[WORKSPACE_ID],
                document_ids=[selected_document_id] * 11,
            ),
        )

    assert caught.value.code == "stop_after_boundary"
    assert calls["resolver"] == (CONFIGURATION_VERSION_ID, MEMBER_ID)
    search_call = calls["search"]
    assert isinstance(search_call, dict)
    assert search_call["actor_id"] == MEMBER_ID
    assert search_call["configuration"] is configuration
    assert configuration.workspace_ids == (WORKSPACE_ID, private_workspace_id)
    downstream_request = search_call["request"]
    assert downstream_request.experimental is True
    assert downstream_request.workspace_ids == [WORKSPACE_ID]
    assert downstream_request.document_ids == [selected_document_id] * 11
