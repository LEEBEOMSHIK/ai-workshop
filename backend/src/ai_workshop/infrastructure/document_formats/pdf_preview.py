from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, cast

import pymupdf

from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryContext,
    TemporaryOwnershipError,
)
from ai_workshop.platform.assets.temporary_service import TemporaryServicePort

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_METADATA_MAX_BYTES = 1024
_WORKER_MODULE = "ai_workshop.infrastructure.document_formats.pdf_preview_worker"
_PDF_OPERATIONAL_ERRORS = (
    pymupdf.FileDataError,
    pymupdf.EmptyFileError,
    RuntimeError,
    OSError,
)


class PdfPreviewError(Exception):
    """Base class for safe PDF preview failures."""


class PdfInvalidError(PdfPreviewError):
    pass


class PdfPageError(PdfPreviewError):
    pass


class PdfPreviewLimitError(PdfPreviewError):
    pass


class PdfPreviewTimeoutError(PdfPreviewError):
    pass


class PdfPreviewWorkerError(PdfPreviewError):
    pass


@dataclass(frozen=True, slots=True)
class PdfInspection:
    page_count: int


@dataclass(frozen=True, slots=True)
class RenderedPdfPage:
    content: bytes
    page_count: int


def inspect_pdf_bytes(content: bytes, *, max_pages: int) -> PdfInspection:
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    document: Any | None = None
    try:
        document = cast(
            Any,
            pymupdf.open(  # type: ignore[no-untyped-call]
                stream=content,
                filetype="pdf",
            ),
        )
        page_count = int(document.page_count)
        if document.needs_pass or not document.is_pdf or page_count < 1:
            raise PdfInvalidError("The PDF is malformed, encrypted or unreadable.")
        if page_count > max_pages:
            raise PdfPreviewLimitError("The PDF exceeds the configured page limit.")
        return PdfInspection(page_count=page_count)
    except (PdfInvalidError, PdfPreviewLimitError):
        raise
    except _PDF_OPERATIONAL_ERRORS as exc:
        raise PdfInvalidError("The PDF is malformed, encrypted or unreadable.") from exc
    finally:
        if document is not None:
            document.close()


def render_pdf_page_bytes(
    content: bytes,
    page_number: int,
    *,
    max_pixels: int | None = None,
) -> bytes:
    if page_number < 1:
        raise PdfPageError("The PDF page number is invalid.")
    if max_pixels is not None and max_pixels < 1:
        raise ValueError("max_pixels must be positive")
    document: Any | None = None
    try:
        document = cast(
            Any,
            pymupdf.open(  # type: ignore[no-untyped-call]
                stream=content,
                filetype="pdf",
            ),
        )
        if page_number > document.page_count:
            raise PdfPageError("The PDF page number is invalid.")
        page = document.load_page(page_number - 1)
        if max_pixels is not None:
            width = float(page.rect.width)
            height = float(page.rect.height)
            if (
                not math.isfinite(width)
                or not math.isfinite(height)
                or width <= 0
                or height <= 0
                or math.ceil(width) * math.ceil(height) > max_pixels
            ):
                raise PdfPreviewLimitError("The PDF page exceeds the configured pixel limit.")
        pixmap = page.get_pixmap(alpha=False)
        if max_pixels is not None and int(pixmap.width) * int(pixmap.height) > max_pixels:
            raise PdfPreviewLimitError("The PDF page exceeds the configured pixel limit.")
        return bytes(pixmap.tobytes("png"))
    except (PdfPageError, PdfPreviewLimitError):
        raise
    except _PDF_OPERATIONAL_ERRORS as exc:
        raise PdfInvalidError("The PDF is malformed, encrypted or unreadable.") from exc
    finally:
        if document is not None:
            document.close()


class PdfPreviewRenderer:
    def __init__(
        self,
        *,
        max_pages: int,
        max_pixels: int,
        timeout_seconds: float,
        max_concurrent: int,
        max_input_bytes: int = 50 * 1024 * 1024,
        temporary_service: TemporaryServicePort | None = None,
        slots: asyncio.Semaphore | None = None,
    ) -> None:
        if (
            max_input_bytes < 1
            or max_pages < 1
            or max_pixels < 1
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
            or max_concurrent < 1
        ):
            raise ValueError("PDF preview limits are invalid.")
        self.max_input_bytes = max_input_bytes
        self.max_pages = max_pages
        self.max_pixels = max_pixels
        self.timeout_seconds = timeout_seconds
        self._slots = slots if slots is not None else asyncio.Semaphore(max_concurrent)
        self._temporary_service = temporary_service
        self._max_output_bytes = max_pixels * 4 + 1024 * 1024

    async def inspect(
        self,
        content: bytes,
        *,
        context: TemporaryContext | None = None,
    ) -> PdfInspection:
        result = await self._run("inspect", content, page_number=None, context=context)
        return PdfInspection(page_count=result["page_count"])

    async def render_page(
        self,
        content: bytes,
        page_number: int,
        *,
        context: TemporaryContext | None = None,
    ) -> RenderedPdfPage:
        if page_number < 1:
            raise PdfPageError("The PDF page number is invalid.")
        result = await self._run("render", content, page_number=page_number, context=context)
        output = result["content"]
        return RenderedPdfPage(content=output, page_count=result["page_count"])

    async def _run(
        self,
        operation: str,
        content: bytes,
        *,
        page_number: int | None,
        context: TemporaryContext | None,
    ) -> dict[str, Any]:
        try:
            return await self._run_process(
                operation,
                content,
                page_number=page_number,
                context=context,
            )
        except (PdfPreviewError, asyncio.CancelledError):
            raise
        except (OSError, subprocess.SubprocessError, TemporaryOwnershipError) as exc:
            raise PdfPreviewWorkerError("The PDF worker is unavailable.") from exc

    async def _run_process(
        self,
        operation: str,
        content: bytes,
        *,
        page_number: int | None,
        context: TemporaryContext | None,
    ) -> dict[str, Any]:
        if len(content) > self.max_input_bytes:
            raise PdfPreviewLimitError("The PDF exceeds the configured input limit.")
        if self._temporary_service is None or context is None:
            raise PdfPreviewWorkerError("Tracked PDF storage is unavailable.")
        async with self._slots:
            lease = await self._temporary_service.open(
                context,
                "pdf_preview",
                coverage="runtime_unverified",
            )
            writer_confirmed = True  # No process has been started yet.

            def reaped() -> None:
                nonlocal writer_confirmed
                writer_confirmed = True

            try:
                root = lease.workspace.root
                input_path = lease.workspace.create_file("input.pdf")
                output_path = lease.workspace.create_file("page.png")
                metadata_path = lease.workspace.create_file("result.json")
                input_path.write_bytes(content)
                command = [
                    sys.executable,
                    "-I",
                    "-m",
                    _WORKER_MODULE,
                    operation,
                    str(input_path),
                    str(output_path),
                    str(metadata_path),
                    str(self.max_input_bytes),
                    str(self.max_pages),
                    str(self.max_pixels),
                    str(self._max_output_bytes),
                ]
                if page_number is not None:
                    command.append(str(page_number))
                # Even a Popen failure can leave uncertain child creation; fail closed.
                writer_confirmed = False
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    close_fds=True,
                    env=_minimal_worker_environment(root),
                    creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
                )
                exit_code = await self._wait(process, on_reaped=reaped)
                if exit_code != 0:
                    _raise_worker_exit(exit_code)
                metadata = _read_metadata(metadata_path, operation)
                if operation == "inspect":
                    return {"page_count": metadata["page_count"]}
                output_size = metadata["output_size"]
                if (
                    output_size > self._max_output_bytes
                    or not output_path.is_file()
                    or output_path.stat().st_size != output_size
                ):
                    raise PdfPreviewWorkerError("The PDF worker returned invalid output.")
                with output_path.open("rb") as source:
                    rendered = source.read(self._max_output_bytes + 1)
                if len(rendered) != output_size or not rendered.startswith(_PNG_SIGNATURE):
                    raise PdfPreviewWorkerError("The PDF worker returned invalid output.")
                return {
                    "page_count": metadata["page_count"],
                    "content": rendered,
                }
            finally:
                await lease.finish(writer_confirmed=writer_confirmed)

    async def _wait(
        self,
        process: subprocess.Popen[bytes],
        *,
        on_reaped: Callable[[], None],
    ) -> int:
        waiter = asyncio.create_task(asyncio.to_thread(process.wait))
        try:
            result = await asyncio.wait_for(
                asyncio.shield(waiter),
                timeout=self.timeout_seconds,
            )
            on_reaped()
            return result
        except TimeoutError as exc:
            cancelled = await _terminate_reap_uninterruptibly(process, waiter)
            on_reaped()
            if cancelled:
                raise asyncio.CancelledError from None
            raise PdfPreviewTimeoutError("The PDF worker timed out.") from exc
        except asyncio.CancelledError:
            await _terminate_reap_uninterruptibly(process, waiter)
            on_reaped()
            raise
        except BaseException:
            cancelled = await _terminate_reap_uninterruptibly(process, waiter)
            on_reaped()
            if cancelled:
                raise asyncio.CancelledError from None
            raise


async def _terminate_reap_uninterruptibly(
    process: subprocess.Popen[bytes],
    waiter: asyncio.Task[int],
) -> bool:
    cleanup = asyncio.create_task(_terminate_and_reap(process, waiter))
    cancelled = False
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            cancelled = True
    cleanup.result()
    return cancelled


async def _terminate_and_reap(
    process: subprocess.Popen[bytes],
    waiter: asyncio.Task[int],
) -> None:
    if process.poll() is None:
        process.terminate()
    try:
        await asyncio.wait_for(asyncio.shield(waiter), timeout=1)
    except TimeoutError:
        if process.poll() is None:
            process.kill()
        await asyncio.shield(waiter)


def _minimal_worker_environment(temp_root: Path) -> dict[str, str]:
    environment = {
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TEMP": str(temp_root),
        "TMP": str(temp_root),
    }
    for name in ("SYSTEMROOT", "WINDIR"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    return environment


def _read_metadata(path: Path, operation: str) -> dict[str, int]:
    try:
        if not path.is_file() or path.stat().st_size > _METADATA_MAX_BYTES:
            raise PdfPreviewWorkerError("The PDF worker returned invalid metadata.")
        with path.open("rb") as source:
            raw_value = source.read(_METADATA_MAX_BYTES + 1)
        if len(raw_value) > _METADATA_MAX_BYTES:
            raise PdfPreviewWorkerError("The PDF worker returned invalid metadata.")
        value = json.loads(raw_value.decode("ascii"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PdfPreviewWorkerError("The PDF worker returned invalid metadata.") from exc
    keys = {"page_count"} if operation == "inspect" else {"page_count", "output_size"}
    if (
        not isinstance(value, dict)
        or set(value) != keys
        or any(
            not isinstance(value[key], int) or isinstance(value[key], bool) or value[key] < 1
            for key in keys
        )
    ):
        raise PdfPreviewWorkerError("The PDF worker returned invalid metadata.")
    return cast(dict[str, int], value)


def _raise_worker_exit(exit_code: int) -> NoReturn:
    if exit_code == 20:
        raise PdfInvalidError("The PDF is malformed, encrypted or unreadable.")
    if exit_code == 21:
        raise PdfPreviewLimitError("The PDF exceeds the configured preview limits.")
    if exit_code == 22:
        raise PdfPageError("The PDF page number is invalid.")
    raise PdfPreviewWorkerError("The PDF worker failed.")
