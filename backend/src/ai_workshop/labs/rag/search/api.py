from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.infrastructure.search.elasticsearch import create_elasticsearch
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchDenseRetriever,
    ElasticsearchSparseRetriever,
)
from ai_workshop.labs.rag.retrieval.scope import (
    SearchScopeResolver,
    SqlAlchemySearchScopeRepository,
)
from ai_workshop.labs.rag.search.configuration_port import (
    SearchConfigurationResolverPort,
)
from ai_workshop.labs.rag.search.repository import SqlAlchemySearchSourceResolver
from ai_workshop.labs.rag.search.schemas import (
    NormalizedElementResponse,
    NormalizedTextResponse,
    SearchRequest,
    SearchResponse,
    SourceLocationResponse,
)
from ai_workshop.labs.rag.search.service import SearchApplicationService
from ai_workshop.labs.rag.search.viewer import ViewerService
from ai_workshop.labs.rag.search.viewer_repository import (
    SqlAlchemyViewerResourceAccessRepository,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import ErrorEnvelope

router = APIRouter(prefix="/api/v1/rag", tags=["rag-search"])


def get_search_configuration_resolver(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchConfigurationResolverPort:
    from ai_workshop.labs.rag.configurations.repository import (
        SqlAlchemySearchConfigurationResolver,
    )

    return SqlAlchemySearchConfigurationResolver(session, settings)


async def get_search_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    configuration_resolver: Annotated[
        SearchConfigurationResolverPort,
        Depends(get_search_configuration_resolver),
    ],
) -> AsyncIterator[SearchApplicationService]:
    client = create_elasticsearch(settings)
    try:
        yield SearchApplicationService(
            configuration_resolver=configuration_resolver,
            scope_resolver=SearchScopeResolver(SqlAlchemySearchScopeRepository(session)),
            sparse_retriever=ElasticsearchSparseRetriever(client),
            dense_retriever=ElasticsearchDenseRetriever(client),
            source_resolver=SqlAlchemySearchSourceResolver(session),
            turn_signer=ConversationTurnSigner(
                settings.secret_key.get_secret_value().encode("utf-8")
            ),
        )
    finally:
        await client.close()


def get_viewer_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> ViewerService:
    return ViewerService(
        SqlAlchemyViewerResourceAccessRepository(session),
        LocalObjectStore(settings.object_store_root),
    )


@router.post(
    "/search",
    response_model=SearchResponse,
    responses={503: {"model": ErrorEnvelope, "description": "Search dependency unavailable."}},
)
async def search(
    request: SearchRequest,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[SearchApplicationService, Depends(get_search_service)],
) -> SearchResponse:
    return SearchResponse.from_domain(await service.search(actor_id=user.id, request=request))


@router.get(
    "/sources/{asset_version_id}/normalized-text",
    response_model=NormalizedTextResponse,
    responses={503: {"model": ErrorEnvelope, "description": "Source object unavailable."}},
)
async def normalized_text(
    asset_version_id: UUID,
    projection_id: Annotated[UUID, Query()],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ViewerService, Depends(get_viewer_service)],
) -> NormalizedTextResponse:
    result = await service.normalized_text(
        actor_id=user.id,
        asset_version_id=asset_version_id,
        projection_id=projection_id,
    )
    resource = result.resource
    return NormalizedTextResponse(
        document_id=resource.document_id,
        asset_version_id=resource.asset_version_id,
        asset_version_number=resource.asset_version_number,
        workspace_id=resource.workspace_id,
        folder_id=resource.folder_id,
        projection_id=resource.projection_id,
        title=resource.title,
        media_type=resource.media_type,
        parser_name=result.document.parser_name,
        parser_version=result.document.parser_version,
        elements=[
            NormalizedElementResponse(
                id=element.id,
                ordinal=element.ordinal,
                kind=element.kind,
                text=element.text,
                section_path=list(element.section_path),
                location=SourceLocationResponse(
                    element_id=element.location.element_id,
                    page=element.location.page,
                    char_start=element.location.char_start,
                    char_end=element.location.char_end,
                    bbox=element.location.bbox,
                ),
                confidence=element.confidence,
            )
            for element in result.document.elements
        ],
    )


@router.get(
    "/sources/{asset_version_id}/pdf/pages/{page_number}",
    response_class=Response,
    responses={
        200: {
            "content": {"image/png": {"schema": {"type": "string", "format": "binary"}}},
            "description": "Authorized immutable PDF page image.",
        },
        503: {"model": ErrorEnvelope, "description": "Source object unavailable."},
    },
)
async def pdf_page(
    asset_version_id: UUID,
    page_number: Annotated[int, Path(ge=1)],
    projection_id: Annotated[UUID, Query()],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[ViewerService, Depends(get_viewer_service)],
) -> Response:
    content = await service.pdf_page(
        actor_id=user.id,
        asset_version_id=asset_version_id,
        projection_id=projection_id,
        page_number=page_number,
    )
    return Response(
        content=content,
        media_type="image/png",
        headers={
            "X-AI-Workshop-Asset-Version": str(asset_version_id),
            "X-AI-Workshop-Projection": str(projection_id),
        },
    )
