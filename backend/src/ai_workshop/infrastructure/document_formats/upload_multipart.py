"""Bounded, allocation-free multipart decoding into a caller-owned destination."""

import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID

from python_multipart.exceptions import MultipartParseError
from python_multipart.multipart import MultipartParser

from ai_workshop.platform.assets.upload_policy import DEFAULT_POLICY, UploadMultipartPolicy
from ai_workshop.shared.errors import AppError

_TOKEN = r"[!#$%&'*+.^_`|~0-9A-Za-z-]+"
_PARAMETER = re.compile(rf';\s*({_TOKEN})\s*=\s*(?:"((?:[^"\\\r\n]|\\[^\r\n])*)"|({_TOKEN}))\s*')
_BOUNDARY = re.compile(rb"[0-9A-Za-z'()+_,./:=? -]+")


def _invalid() -> AppError:
    return AppError("upload_multipart_invalid", "The multipart upload is invalid.", 422)


def _too_large() -> AppError:
    return AppError("upload_too_large", "The upload exceeds the permitted size.", 413)


def _parameters(value: str) -> tuple[str, dict[str, str]]:
    """Parse a strict parameter list without silently collapsing duplicate keys."""
    if any(ord(char) < 32 and char != "\t" or ord(char) == 127 for char in value):
        raise _invalid()
    first, _, rest = value.partition(";")
    params: dict[str, str] = {}
    pending = ";" + rest if ";" in value else ""
    while pending:
        match = _PARAMETER.match(pending)
        if match is None:
            raise _invalid()
        key = match[1].lower()
        if key in params:
            raise _invalid()
        params[key] = re.sub(r"\\(.)", r"\1", match[2]) if match[2] is not None else match[3]
        pending = pending[match.end() :]
    return first.strip().lower(), params


@dataclass(frozen=True, slots=True)
class ParsedUpload:
    filename: str
    media_type: str
    folder_id: UUID | None
    size: int


class _Upload:
    def __init__(self, destination: BinaryIO, allow_folder: bool, policy: UploadMultipartPolicy):
        self.destination = destination
        self.allow_folder = allow_folder
        self.policy = policy
        self.headers: dict[bytes, bytes] = {}
        self.header_name = bytearray()
        self.header_value = bytearray()
        self.field = bytearray()
        self.part = ""
        self.seen: set[str] = set()
        self.filename = ""
        self.media_type = "application/octet-stream"
        self.folder_id: UUID | None = None
        self.size = 0
        self.file_complete = False
        self.ended = False

    def part_begin(self) -> None:
        self.headers.clear()
        self.part = ""

    def header_field(self, data: bytes, start: int, end: int) -> None:
        self.header_name.extend(data[start:end])

    def header_value_data(self, data: bytes, start: int, end: int) -> None:
        self.header_value.extend(data[start:end])

    def header_end(self) -> None:
        name = bytes(self.header_name).lower()
        if (
            name not in {b"content-disposition", b"content-type"}
            or name in self.headers
            or len(self.headers) >= self.policy.max_headers
        ):
            raise _invalid()
        self.headers[name] = bytes(self.header_value)
        self.header_name.clear()
        self.header_value.clear()

    def headers_finished(self) -> None:
        raw = self.headers.get(b"content-disposition", b"")
        try:
            disposition = raw.decode("utf-8")
        except UnicodeDecodeError:
            disposition = raw.decode("latin-1")
        kind, params = _parameters(disposition)
        if kind != "form-data" or not set(params) <= {"name", "filename"}:
            raise _invalid()
        self.part = params.get("name", "")
        if self.part in self.seen or self.part not in {"file", "folder_id"}:
            raise _invalid()
        self.seen.add(self.part)
        if self.part == "file":
            self.filename = params.get("filename", "")
            if not self.filename or any(ord(c) < 32 or ord(c) == 127 for c in self.filename):
                raise _invalid()
            if b"content-type" in self.headers:
                try:
                    self.media_type = self.headers[b"content-type"].decode("ascii")
                except UnicodeDecodeError:
                    raise _invalid() from None
                media, _ = _parameters(self.media_type)
                if re.fullmatch(rf"{_TOKEN}/{_TOKEN}", media) is None:
                    raise _invalid()
        elif not self.allow_folder or "filename" in params or b"content-type" in self.headers:
            raise _invalid()

    def part_data(self, data: bytes, start: int, end: int) -> None:
        count = end - start
        if self.part == "file":
            if self.size + count > self.policy.max_file_bytes:
                raise _too_large()
            try:
                written = self.destination.write(data[start:end])
            except (OSError, ValueError):
                raise AppError(
                    "upload_write_failed", "The upload could not be stored.", 500
                ) from None
            if written != count:
                raise AppError("upload_write_failed", "The upload could not be stored.", 500)
            self.size += count
        elif self.part == "folder_id":
            if len(self.field) + count > self.policy.max_field_bytes:
                raise _too_large()
            self.field.extend(data[start:end])
        else:
            raise _invalid()

    def part_end(self) -> None:
        if self.part == "file":
            if self.size == 0:
                raise _invalid()
            self.file_complete = True
        elif self.part == "folder_id":
            try:
                self.folder_id = UUID(self.field.decode("ascii"))
            except (ValueError, UnicodeDecodeError):
                raise _invalid() from None
        else:
            raise _invalid()

    def end(self) -> None:
        self.ended = True


async def parse_upload(
    stream: AsyncIterator[bytes],
    content_type: str,
    destination: BinaryIO,
    *,
    allow_folder: bool,
    policy: UploadMultipartPolicy = DEFAULT_POLICY,
) -> ParsedUpload:
    if len(content_type) > policy.max_header_bytes:
        raise _too_large()
    media, params = _parameters(content_type)
    if media != "multipart/form-data" or set(params) != {"boundary"}:
        raise _invalid()
    try:
        boundary = params["boundary"].encode("ascii")
    except UnicodeEncodeError:
        raise _invalid() from None
    if len(boundary) > policy.max_boundary_bytes:
        raise _too_large()
    if not boundary or not _BOUNDARY.fullmatch(boundary) or boundary.endswith(b" "):
        raise _invalid()
    upload = _Upload(destination, allow_folder, policy)
    parser = MultipartParser(
        boundary,
        callbacks={
            "on_part_begin": upload.part_begin,
            "on_header_field": upload.header_field,
            "on_header_value": upload.header_value_data,
            "on_header_end": upload.header_end,
            "on_headers_finished": upload.headers_finished,
            "on_part_data": upload.part_data,
            "on_part_end": upload.part_end,
            "on_end": upload.end,
        },
    )
    # The library logs malformed raw byte values. Disable only this instance's
    # diagnostics; caller receives fixed errors, without global logger mutation.
    parser.logger = logging.Logger("upload_multipart_private")
    parser.logger.disabled = True

    def feed(data: bytes) -> None:
        # A retained delimiter prefix can make pending exceed one input slice.
        for start in range(0, len(data), policy.slice_bytes):
            parser.write(data[start : start + policy.slice_bytes])

    prefix = b"--" + boundary + b"\r\n"
    delimiter = b"\r\n--" + boundary
    pending = b""
    mode = "start"
    header_bytes = 0
    header_tail = b""
    total = 0
    try:
        async for chunk in stream:
            total += len(chunk)
            if total > policy.max_file_bytes + policy.envelope_bytes:
                raise _too_large()
            for offset in range(0, len(chunk), policy.slice_bytes):
                pending += chunk[offset : offset + policy.slice_bytes]
                while pending:
                    if mode == "start":
                        if not prefix.startswith(pending[: len(prefix)]):
                            raise _invalid()
                        if len(pending) < len(prefix):
                            break
                        feed(prefix)
                        pending = pending[len(prefix) :]
                        mode = "headers"
                    elif mode == "headers":
                        # Only the small bounded header block is byte-stepped.
                        # This counts spaces and framing that callbacks omit.
                        byte, pending = pending[:1], pending[1:]
                        header_bytes += 1
                        if header_bytes > policy.max_header_bytes:
                            raise _too_large()
                        feed(byte)
                        header_tail = (header_tail + byte)[-4:]
                        if header_tail == b"\r\n\r\n":
                            mode = "body"
                            header_tail = b""
                            header_bytes = 0
                    elif mode == "body":
                        index = pending.find(delimiter)
                        if index < 0:
                            safe = len(pending) - len(delimiter) - 1
                            if safe <= 0:
                                break
                            feed(pending[:safe])
                            pending = pending[safe:]
                        elif len(pending) < index + len(delimiter) + 2:
                            feed(pending[:index])
                            pending = pending[index:]
                            break
                        else:
                            end = index + len(delimiter) + 2
                            suffix = pending[end - 2 : end]
                            if suffix not in {b"--", b"\r\n"}:
                                # A boundary-like sequence inside payload is data.
                                feed(pending[: index + 2])
                                pending = pending[index + 2 :]
                                continue
                            feed(pending[:end])
                            pending = pending[end:]
                            mode = "trailer" if suffix == b"--" else "headers"
                            if mode == "trailer" and not upload.ended:
                                raise _invalid()
                    else:
                        if pending not in {b"\r", b"\r\n"}:
                            raise _invalid()
                        break
        if mode != "trailer" or pending not in {b"", b"\r\n"}:
            raise _invalid()
        parser.finalize()
    except MultipartParseError:
        raise _invalid() from None
    if not upload.ended or not upload.file_complete:
        raise _invalid()
    return ParsedUpload(upload.filename, upload.media_type, upload.folder_id, upload.size)
