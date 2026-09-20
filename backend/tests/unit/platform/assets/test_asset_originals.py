from collections.abc import AsyncIterator
from dataclasses import replace
from hashlib import sha256
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse
from pydantic import ValidationError

from ai_workshop.config import Settings
from ai_workshop.infrastructure.document_formats.pdf_preview import (
    PdfInspection,
    PdfInvalidError,
    PdfPageError,
    PdfPreviewLimitError,
    PdfPreviewTimeoutError,
    PdfPreviewWorkerError,
    RenderedPdfPage,
)
from ai_workshop.main import create_app
from ai_workshop.platform.assets.domain import VersionStatus
from ai_workshop.platform.assets.originals import (
    OriginalResource,
    OriginalService,
)
from ai_workshop.platform.assets.originals_api import get_original_service
from ai_workshop.platform.assets.provenance_contracts import SourceIdentity
from ai_workshop.platform.assets.temporary_contracts import TemporaryContext
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.errors import AppError


def settings(**overrides: object) -> Settings:
    return Settings(
        secret_key="test-secret-key-that-is-at-least-thirty-two-characters",
        _env_file=None,
        **overrides,
    )


def test_original_preview_settings_have_bounded_defaults() -> None:
    configured = settings()

    assert configured.original_max_bytes == 50 * 1024 * 1024
    assert configured.text_preview_max_bytes == 2 * 1024 * 1024
    assert configured.pdf_max_pages == 1000
    assert configured.pdf_max_pixels == 16_000_000
    assert configured.pdf_timeout_seconds == 15
    assert configured.pdf_max_concurrent == 2


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("original_max_bytes", 0),
        ("text_preview_max_bytes", 0),
        ("pdf_max_pages", 0),
        ("pdf_max_pixels", 0),
        ("pdf_timeout_seconds", 0),
        ("pdf_max_concurrent", 0),
    ],
)
def test_original_preview_settings_reject_nonpositive_bounds(
    name: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError):
        settings(**{name: value})


def test_text_preview_bound_cannot_exceed_original_bound() -> None:
    with pytest.raises(ValidationError):
        settings(original_max_bytes=10, text_preview_max_bytes=11)


ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
DOCUMENT_ID = UUID("20000000-0000-0000-0000-000000000001")
VERSION_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("40000000-0000-0000-0000-000000000001")


def member() -> User:
    return User(
        id=ACTOR_ID,
        display_name="Synthetic member",
        email="member@example.test",
        normalized_email="member@example.test",
        password_hash="synthetic-password-hash",
        role=UserRole.MEMBER,
    )


def original_resource(
    content: bytes,
    *,
    suffix: str = ".md",
    media_type: str = "application/octet-stream",
    status: VersionStatus = VersionStatus.READY,
    name: str = "합성 문서.md",
) -> OriginalResource:
    return OriginalResource(
        document_id=DOCUMENT_ID,
        workspace_id=WORKSPACE_ID,
        asset_version_id=VERSION_ID,
        version=1,
        name=name,
        object_key=f"synthetic/immutable{suffix}",
        sha256=sha256(content).hexdigest(),
        size=len(content),
        media_type=media_type,
        status=status,
    )


class MemoryOriginalRepository:
    def __init__(self, results: list[OriginalResource | None]) -> None:
        self.results = results
        self.calls: list[tuple[UUID, UUID, UUID]] = []

    async def resolve(
        self,
        *,
        user_id: UUID,
        document_id: UUID,
        version_id: UUID,
    ) -> OriginalResource | None:
        self.calls.append((user_id, document_id, version_id))
        if len(self.results) > 1:
            return self.results.pop(0)
        return self.results[0]


class MemoryObjectStore:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.opens: list[str] = []

    async def put(self, key: str, source: AsyncIterator[bytes]) -> object:
        del key, source
        raise AssertionError("preview never writes storage")

    async def open(self, key: str) -> AsyncIterator[bytes]:
        self.opens.append(key)
        if key not in self.objects:
            raise FileNotFoundError
        content = self.objects[key]
        midpoint = len(content) // 2
        for chunk in (content[:midpoint], content[midpoint:]):
            if chunk:
                yield chunk

    async def delete(self, key: str) -> None:
        del key
        raise AssertionError("preview never deletes storage")


class MemoryPdfRenderer:
    def __init__(self) -> None:
        self.inspected: list[bytes] = []
        self.contexts: list[TemporaryContext] = []
        self.rendered: list[tuple[bytes, int]] = []

    async def inspect(self, content: bytes, *, context: TemporaryContext) -> PdfInspection:
        self.inspected.append(content)
        self.contexts.append(context)
        return PdfInspection(page_count=2)

    async def render_page(
        self, content: bytes, page_number: int, *, context: TemporaryContext
    ) -> RenderedPdfPage:
        self.rendered.append((content, page_number))
        self.contexts.append(context)
        return RenderedPdfPage(
            content=b"\x89PNG\r\n\x1a\nsynthetic",
            page_count=2,
        )


class FailingPdfRenderer(MemoryPdfRenderer):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def inspect(self, content: bytes, *, context: TemporaryContext) -> PdfInspection:
        del content
        raise self.error

    async def render_page(
        self, content: bytes, page_number: int, *, context: TemporaryContext
    ) -> RenderedPdfPage:
        del content, page_number
        raise self.error


def original_service(
    repository: MemoryOriginalRepository,
    store: MemoryObjectStore,
    renderer: MemoryPdfRenderer | None = None,
    *,
    original_max_bytes: int = 1024,
    text_preview_max_bytes: int = 512,
) -> OriginalService:
    return OriginalService(
        repository,
        store,
        renderer or MemoryPdfRenderer(),
        original_max_bytes=original_max_bytes,
        text_preview_max_bytes=text_preview_max_bytes,
    )


@pytest.mark.asyncio
async def test_historic_ready_text_preserves_bom_nonbmp_and_uses_exact_suffix() -> None:
    content = b"\xef\xbb\xbf" + "합성 문서\n안녕하세요 🧪".encode()
    resource = original_resource(content, suffix=".txt", media_type="application/pdf")
    repository = MemoryOriginalRepository([resource])
    store = MemoryObjectStore({resource.object_key: content})

    preview = await original_service(repository, store).preview(
        user=member(),
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
    )

    assert preview.text == "합성 문서\n안녕하세요 🧪"
    assert preview.kind == "text"
    assert preview.asset_version_id == VERSION_ID
    assert preview.version == 1
    assert repository.calls == [
        (ACTOR_ID, DOCUMENT_ID, VERSION_ID),
        (ACTOR_ID, DOCUMENT_ID, VERSION_ID),
    ]


@pytest.mark.asyncio
async def test_foreign_or_missing_version_is_denied_before_storage_read() -> None:
    store = MemoryObjectStore({})

    with pytest.raises(AppError) as failure:
        await original_service(MemoryOriginalRepository([None]), store).preview(
            user=member(),
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
        )

    assert failure.value.status_code == 404
    assert store.opens == []


@pytest.mark.asyncio
async def test_nonready_version_is_conflict_before_storage_read() -> None:
    content = b"pending"
    resource = original_resource(content, status=VersionStatus.PROCESSING)
    store = MemoryObjectStore({resource.object_key: content})

    with pytest.raises(AppError) as failure:
        await original_service(MemoryOriginalRepository([resource]), store).preview(
            user=member(),
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
        )

    assert failure.value.status_code == 409
    assert store.opens == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_kind", ["missing", "size", "sha256"])
async def test_missing_or_corrupt_original_fails_without_returning_content(
    failure_kind: str,
) -> None:
    content = b"verified text"
    resource = original_resource(content)
    objects = {resource.object_key: content}
    if failure_kind == "missing":
        objects = {}
    elif failure_kind == "size":
        objects[resource.object_key] = content + b"!"
    else:
        resource = replace(resource, sha256="0" * 64)

    with pytest.raises(AppError) as failure:
        await original_service(
            MemoryOriginalRepository([resource]),
            MemoryObjectStore(objects),
        ).preview(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)

    assert failure.value.status_code == 503
    assert content.decode() not in failure.value.message
    assert resource.object_key not in failure.value.message


@pytest.mark.asyncio
async def test_original_size_limit_rejects_before_storage_read() -> None:
    content = b"x" * 33
    resource = original_resource(content)
    store = MemoryObjectStore({resource.object_key: content})

    with pytest.raises(AppError) as failure:
        await original_service(
            MemoryOriginalRepository([resource]),
            store,
            original_max_bytes=32,
            text_preview_max_bytes=32,
        ).content(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)

    assert failure.value.status_code == 413
    assert store.opens == []


@pytest.mark.asyncio
async def test_text_preview_limit_and_strict_utf8_are_explicit_422_or_413() -> None:
    too_long = b"x" * 9
    too_long_resource = original_resource(too_long)
    with pytest.raises(AppError) as oversize:
        await original_service(
            MemoryOriginalRepository([too_long_resource]),
            MemoryObjectStore({too_long_resource.object_key: too_long}),
            text_preview_max_bytes=8,
        ).preview(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)

    invalid = b"valid-prefix\xff"
    invalid_resource = original_resource(invalid, suffix=".txt")
    with pytest.raises(AppError) as encoding:
        await original_service(
            MemoryOriginalRepository([invalid_resource]),
            MemoryObjectStore({invalid_resource.object_key: invalid}),
        ).preview(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)

    assert oversize.value.status_code == 413
    assert encoding.value.status_code == 422


@pytest.mark.asyncio
async def test_pdf_requires_pdf_bytes_and_uses_same_verified_bytes_for_worker() -> None:
    content = b"%PDF-1.7\nsynthetic"
    resource = original_resource(content, suffix=".pdf", media_type="text/plain")
    renderer = MemoryPdfRenderer()
    service = original_service(
        MemoryOriginalRepository([resource]),
        MemoryObjectStore({resource.object_key: content}),
        renderer,
    )

    metadata = await service.preview(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)
    page = await service.pdf_page(
        user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID, page_number=2
    )

    assert metadata.kind == "pdf"
    assert metadata.page_count == 2
    assert page == b"\x89PNG\r\n\x1a\nsynthetic"
    assert renderer.inspected == [content]
    assert renderer.rendered == [(content, 2)]
    assert (
        renderer.contexts
        == [TemporaryContext(SourceIdentity(resource.workspace_id, DOCUMENT_ID, VERSION_ID))] * 2
    )

    invalid = b"not a pdf"
    invalid_resource = original_resource(invalid, suffix=".pdf")
    with pytest.raises(AppError) as failure:
        await original_service(
            MemoryOriginalRepository([invalid_resource]),
            MemoryObjectStore({invalid_resource.object_key: invalid}),
        ).preview(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)
    assert failure.value.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (PdfInvalidError(), 422),
        (PdfPageError(), 422),
        (PdfPreviewLimitError(), 413),
        (PdfPreviewTimeoutError(), 503),
        (PdfPreviewWorkerError(), 503),
    ],
)
async def test_pdf_worker_failures_map_to_safe_original_errors(
    error: Exception,
    expected_status: int,
) -> None:
    content = b"%PDF-1.7\nsynthetic"
    resource = original_resource(content, suffix=".pdf")
    service = original_service(
        MemoryOriginalRepository([resource]),
        MemoryObjectStore({resource.object_key: content}),
        FailingPdfRenderer(error),
    )

    with pytest.raises(AppError) as failure:
        await service.preview(
            user=member(),
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
        )

    assert failure.value.status_code == expected_status
    assert content.decode() not in failure.value.message


@pytest.mark.asyncio
async def test_unsupported_preview_is_metadata_only_but_download_remains_available() -> None:
    content = b"<html><script>never execute</script></html>"
    resource = original_resource(content, suffix=".html", name="report.html")
    service = original_service(
        MemoryOriginalRepository([resource]),
        MemoryObjectStore({resource.object_key: content}),
    )

    preview = await service.preview(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)
    download = await service.content(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)

    assert preview.kind == "unsupported"
    assert preview.text is None
    assert preview.page_count is None
    assert download.content == content
    assert download.content_disposition == (
        "attachment; filename=\"report.html\"; filename*=UTF-8''report.html"
    )


@pytest.mark.asyncio
async def test_final_authorization_recheck_denies_revoked_access() -> None:
    content = b"authorized then revoked"
    resource = original_resource(content)
    repository = MemoryOriginalRepository([resource, None])

    with pytest.raises(AppError) as failure:
        await original_service(
            repository,
            MemoryObjectStore({resource.object_key: content}),
        ).content(user=member(), document_id=DOCUMENT_ID, version_id=VERSION_ID)

    assert failure.value.status_code == 404
    assert len(repository.calls) == 2


def test_original_routes_return_private_nosniff_metadata_png_and_attachment() -> None:
    text = "합성 원문 🧪".encode()
    resource = original_resource(text, name="보고서\r\nInjected: yes.md")
    service = original_service(
        MemoryOriginalRepository([resource]),
        MemoryObjectStore({resource.object_key: text}),
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = member
    app.dependency_overrides[get_original_service] = lambda: service

    with TestClient(app) as client:
        preview = client.get(f"/api/v1/documents/{DOCUMENT_ID}/versions/{VERSION_ID}/preview")
        content = client.get(f"/api/v1/documents/{DOCUMENT_ID}/versions/{VERSION_ID}/content")

    assert preview.status_code == 200
    assert preview.json()["text"] == "합성 원문 🧪"
    for response in (preview, content):
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
    disposition = content.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert disposition.startswith("attachment;")
    assert content.content == text


def test_pdf_page_route_returns_only_bounded_png_with_private_headers() -> None:
    pdf = b"%PDF-1.7\nsynthetic"
    resource = original_resource(pdf, suffix=".pdf", name="synthetic.pdf")
    service = original_service(
        MemoryOriginalRepository([resource]),
        MemoryObjectStore({resource.object_key: pdf}),
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = member
    app.dependency_overrides[get_original_service] = lambda: service

    with TestClient(app) as client:
        response = client.get(f"/api/v1/documents/{DOCUMENT_ID}/versions/{VERSION_ID}/pdf/pages/2")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.content == b"\x89PNG\r\n\x1a\nsynthetic"


def _assert_private_original_error(
    response: HttpxResponse,
    expected_status: int,
) -> None:
    assert response.status_code == expected_status
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_original_route_errors_are_private_for_auth_validation_and_app_errors() -> None:
    missing_service = original_service(
        MemoryOriginalRepository([None]),
        MemoryObjectStore({}),
    )

    app_error_app = create_app()
    app_error_app.dependency_overrides[get_current_user] = member
    app_error_app.dependency_overrides[get_original_service] = lambda: missing_service
    with TestClient(app_error_app) as client:
        missing = client.get(f"/api/v1/documents/{DOCUMENT_ID}/versions/{VERSION_ID}/preview")

    def unauthorized() -> User:
        raise AppError("authentication_required", "Authentication is required.", 401)

    auth_app = create_app()
    auth_app.dependency_overrides[get_current_user] = unauthorized
    auth_app.dependency_overrides[get_original_service] = lambda: missing_service
    with TestClient(auth_app) as client:
        auth = client.get(f"/api/v1/documents/{DOCUMENT_ID}/versions/{VERSION_ID}/content")

    validation_app = create_app()
    validation_app.dependency_overrides[get_current_user] = member
    validation_app.dependency_overrides[get_original_service] = lambda: missing_service
    with TestClient(validation_app) as client:
        validation = client.get(
            f"/api/v1/documents/{DOCUMENT_ID}/versions/{VERSION_ID}/pdf/pages/0"
        )

    _assert_private_original_error(missing, 404)
    _assert_private_original_error(auth, 401)
    _assert_private_original_error(validation, 422)
