import pytest

from ai_workshop.infrastructure.document_formats import pdf_preview as module
from tests.unit.infrastructure.document_formats.temporary_preview_support import (
    CONTEXT,
    FakeTemporaryService,
)
from tests.unit.infrastructure.document_formats.test_pdf_preview import two_page_pdf


def renderer(service=None):
    return module.PdfPreviewRenderer(
        max_pages=2,
        max_pixels=20000,
        timeout_seconds=5,
        max_concurrent=1,
        temporary_service=service,
    )


@pytest.mark.asyncio
async def test_requires_source_and_tracking_before_spawning(monkeypatch):
    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("spawn"))
    with pytest.raises(module.PdfPreviewWorkerError):
        await renderer().inspect(two_page_pdf(), context=CONTEXT)


@pytest.mark.asyncio
async def test_tracks_real_worker_and_preallocated_outputs(tmp_path):
    service = FakeTemporaryService(tmp_path)
    result = await renderer(service).render_page(two_page_pdf(), 1, context=CONTEXT)
    assert result.content.startswith(b"\x89PNG")
    assert service.contexts == [(CONTEXT, "pdf_preview", "runtime_unverified")]
    assert service.leases[0].confirmed is True
    assert {p.name for p in service.leases[0].workspace.root.iterdir()} == {
        "input.pdf",
        "page.png",
        "result.json",
    }


@pytest.mark.asyncio
async def test_termination_failure_preserves_open_workspace(tmp_path, monkeypatch):
    class Process:
        returncode = None

        def wait(self):
            raise OSError("synthetic wait failure")

        def poll(self):
            return None

        def terminate(self):
            raise OSError("synthetic termination failure")

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: Process())
    service = FakeTemporaryService(tmp_path)
    with pytest.raises(module.PdfPreviewWorkerError):
        await renderer(service).inspect(two_page_pdf(), context=CONTEXT)
    assert service.leases[0].confirmed is False
    assert (service.leases[0].workspace.root / "input.pdf").exists()


@pytest.mark.asyncio
async def test_reservation_failure_never_writes_or_spawns(tmp_path, monkeypatch):
    class Unavailable:
        async def open(self, *args, **kwargs):
            raise OSError("synthetic reservation failure")

    monkeypatch.setattr(module.subprocess, "Popen", lambda *a, **k: pytest.fail("spawn"))
    with pytest.raises(module.PdfPreviewWorkerError):
        await renderer(Unavailable()).inspect(two_page_pdf(), context=CONTEXT)
    assert list(tmp_path.iterdir()) == []
