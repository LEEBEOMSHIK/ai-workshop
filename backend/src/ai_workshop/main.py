from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_workshop.labs.rag.configurations.api import router as rag_configuration_router
from ai_workshop.labs.rag.conversations.api import router as rag_conversation_router
from ai_workshop.labs.rag.conversations.attachment_api import (
    cleanup_router as rag_attachment_cleanup_router,
)
from ai_workshop.labs.rag.conversations.attachment_api import router as rag_attachment_router
from ai_workshop.labs.rag.deployments.api import router as rag_deployment_router
from ai_workshop.labs.rag.domains.api import admin_router as rag_domain_admin_router
from ai_workshop.labs.rag.domains.api import router as rag_domain_router
from ai_workshop.labs.rag.evaluation.api import router as rag_evaluation_router
from ai_workshop.labs.rag.evaluation.authoring_api import router as rag_authoring_router
from ai_workshop.labs.rag.generation.codex_admin_api import router as rag_codex_admin_router
from ai_workshop.labs.rag.generation.evidence_approval_request_api import (
    router as rag_evidence_request_router,
)
from ai_workshop.labs.rag.models.admin_api import router as rag_model_admin_router
from ai_workshop.labs.rag.models.api import router as rag_model_router
from ai_workshop.labs.rag.policies.api import router as rag_policy_router
from ai_workshop.labs.rag.search.api import router as rag_search_router
from ai_workshop.platform.assets.api import router as asset_router
from ai_workshop.platform.identity.api import router as identity_router
from ai_workshop.platform.identity.authorization_api import (
    AuthorizationCacheControlMiddleware,
)
from ai_workshop.platform.identity.authorization_api import router as authorization_router
from ai_workshop.platform.jobs.api import router as job_router
from ai_workshop.platform.learning.api import router as learning_router
from ai_workshop.platform.publishing.api import router as publishing_router
from ai_workshop.platform.publishing.http import NoStoreMiddleware
from ai_workshop.platform.runtime_topology.api import router as runtime_topology_router
from ai_workshop.platform.setup.api import router as setup_router
from ai_workshop.platform.workspaces.api import router as workspace_router
from ai_workshop.shared.errors import COMMON_ERROR_RESPONSES, register_error_handlers
from ai_workshop.shared.request_context import CorrelationIdMiddleware


def create_app() -> FastAPI:
    application = FastAPI(
        title="AI Workshop API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        responses=COMMON_ERROR_RESPONSES,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_middleware(CorrelationIdMiddleware)
    application.add_middleware(AuthorizationCacheControlMiddleware)
    application.add_middleware(NoStoreMiddleware, path_prefix="/api/v1/rag/domains")
    application.add_middleware(
        NoStoreMiddleware,
        path_prefix="/api/v1/admin/publishing",
    )
    register_error_handlers(application)
    application.include_router(asset_router)
    application.include_router(authorization_router)
    application.include_router(identity_router)
    application.include_router(job_router)
    application.include_router(learning_router)
    application.include_router(publishing_router)
    application.include_router(runtime_topology_router)
    application.include_router(rag_configuration_router)
    application.include_router(rag_codex_admin_router)
    application.include_router(rag_evidence_request_router)
    application.include_router(rag_deployment_router)
    application.include_router(rag_domain_router)
    application.include_router(rag_conversation_router)
    application.include_router(rag_attachment_router)
    application.include_router(rag_attachment_cleanup_router)
    application.include_router(rag_domain_admin_router)
    application.include_router(rag_evaluation_router)
    application.include_router(rag_authoring_router)
    application.include_router(rag_model_router)
    application.include_router(rag_model_admin_router)
    application.include_router(rag_policy_router)
    application.include_router(rag_search_router)
    application.include_router(setup_router)
    application.include_router(workspace_router)

    @application.get("/api/v1/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
