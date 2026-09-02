from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_workshop.labs.rag.configurations.api import router as rag_configuration_router
from ai_workshop.labs.rag.evaluation.api import router as rag_evaluation_router
from ai_workshop.labs.rag.models.api import router as rag_model_router
from ai_workshop.labs.rag.search.api import router as rag_search_router
from ai_workshop.platform.assets.api import router as asset_router
from ai_workshop.platform.identity.api import router as identity_router
from ai_workshop.platform.jobs.api import router as job_router
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
    register_error_handlers(application)
    application.include_router(asset_router)
    application.include_router(identity_router)
    application.include_router(job_router)
    application.include_router(rag_configuration_router)
    application.include_router(rag_evaluation_router)
    application.include_router(rag_model_router)
    application.include_router(rag_search_router)
    application.include_router(setup_router)
    application.include_router(workspace_router)

    @application.get("/api/v1/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
