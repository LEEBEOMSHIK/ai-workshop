from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import lru_cache
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from ai_workshop.config import Settings, get_settings
from ai_workshop.infrastructure.document_formats.pdf_preview import PdfPreviewRenderer
from ai_workshop.infrastructure.object_store.local import LocalObjectStore
from ai_workshop.platform.assets.originals import (
    OriginalPreview,
    OriginalService,
    SqlAlchemyOriginalRepository,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError

_PRIVATE_HEADERS = {
    "Cache-Control": "private, no-store",
    "Pragma": "no-cache",
    "X-Content-Type-Options": "nosniff",
}


class _PrivateOriginalRoute(APIRoute):
    def get_route_handler(
        self,
    ) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def private_handler(request: Request) -> Response:
            try:
                response = await handler(request)
            except AppError as exc:
                response = _original_error_response(
                    request,
                    code=exc.code,
                    message=exc.message,
                    status_code=exc.status_code,
                )
            except RequestValidationError:
                response = _original_error_response(
                    request,
                    code="validation_error",
                    message="The request data is invalid.",
                    status_code=422,
                )
            except StarletteHTTPException as exc:
                response = _original_error_response(
                    request,
                    code="not_found" if exc.status_code == 404 else "http_error",
                    message=(
                        "The requested resource was not found."
                        if exc.status_code == 404
                        else "The request could not be completed."
                    ),
                    status_code=exc.status_code,
                )
            response.headers.update(_PRIVATE_HEADERS)
            return response

        return private_handler


def _original_error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", "unavailable")
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "correlation_id": correlation_id,
            }
        },
        headers=_PRIVATE_HEADERS,
    )


router = APIRouter(tags=["asset-originals"], route_class=_PrivateOriginalRoute)


class OriginalPreviewResponse(BaseModel):
    document_id: UUID
    asset_version_id: UUID
    version: int
    name: str
    kind: Literal["text", "markdown", "pdf", "unsupported"]
    size: int
    text: str | None
    page_count: int | None

    @classmethod
    def from_domain(cls, value: OriginalPreview) -> OriginalPreviewResponse:
        return cls(
            document_id=value.document_id,
            asset_version_id=value.asset_version_id,
            version=value.version,
            name=value.name,
            kind=value.kind,
            size=value.size,
            text=value.text,
            page_count=value.page_count,
        )


@lru_cache(maxsize=16)
def _renderer(
    original_max_bytes: int,
    pdf_max_pages: int,
    pdf_max_pixels: int,
    pdf_timeout_seconds: int,
    pdf_max_concurrent: int,
) -> PdfPreviewRenderer:
    return PdfPreviewRenderer(
        max_input_bytes=original_max_bytes,
        max_pages=pdf_max_pages,
        max_pixels=pdf_max_pixels,
        timeout_seconds=pdf_timeout_seconds,
        max_concurrent=pdf_max_concurrent,
    )


def get_original_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OriginalService:
    return OriginalService(
        SqlAlchemyOriginalRepository(session),
        LocalObjectStore(settings.object_store_root),
        _renderer(
            settings.original_max_bytes,
            settings.pdf_max_pages,
            settings.pdf_max_pixels,
            settings.pdf_timeout_seconds,
            settings.pdf_max_concurrent,
        ),
        original_max_bytes=settings.original_max_bytes,
        text_preview_max_bytes=settings.text_preview_max_bytes,
    )


@router.get(
    "/documents/{document_id}/versions/{version_id}/preview",
    response_model=OriginalPreviewResponse,
)
async def preview_original(
    document_id: UUID,
    version_id: UUID,
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OriginalService, Depends(get_original_service)],
) -> OriginalPreviewResponse:
    result = await service.preview(
        user=user,
        document_id=document_id,
        version_id=version_id,
    )
    response.headers.update(_PRIVATE_HEADERS)
    return OriginalPreviewResponse.from_domain(result)


@router.get(
    "/documents/{document_id}/versions/{version_id}/pdf/pages/{page_number}",
    response_class=Response,
)
async def preview_pdf_page(
    document_id: UUID,
    version_id: UUID,
    page_number: Annotated[int, Path(ge=1)],
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OriginalService, Depends(get_original_service)],
) -> Response:
    content = await service.pdf_page(
        user=user,
        document_id=document_id,
        version_id=version_id,
        page_number=page_number,
    )
    return Response(content=content, media_type="image/png", headers=_PRIVATE_HEADERS)


@router.get(
    "/documents/{document_id}/versions/{version_id}/content",
    response_class=Response,
)
async def download_original(
    document_id: UUID,
    version_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OriginalService, Depends(get_original_service)],
) -> Response:
    result = await service.content(
        user=user,
        document_id=document_id,
        version_id=version_id,
    )
    return Response(
        content=result.content,
        media_type="application/octet-stream",
        headers={
            **_PRIVATE_HEADERS,
            "Content-Disposition": result.content_disposition,
        },
    )
