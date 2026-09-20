from collections.abc import AsyncIterator
from io import BytesIO
from uuid import UUID

import pytest

from ai_workshop.infrastructure.document_formats.upload_multipart import parse_upload
from ai_workshop.platform.assets.upload_policy import UploadMultipartPolicy
from ai_workshop.shared.errors import AppError

FOLDER = b"12345678-1234-1234-1234-123456789abc"


def body(parts: list[tuple[bytes, bytes]], boundary: bytes = b"test") -> bytes:
    return (
        b"".join(
            b"--" + boundary + b"\r\n" + headers + b"\r\n\r\n" + data + b"\r\n"
            for headers, data in parts
        )
        + b"--"
        + boundary
        + b"--\r\n"
    )


FILE = (
    b'Content-Disposition: form-data; name="file"; filename="sample.txt"'
    b"\r\nContent-Type: text/plain"
)
FIELD = b'Content-Disposition: form-data; name="folder_id"'


async def chunks(data: bytes, split: int = 65536) -> AsyncIterator[bytes]:
    for offset in range(0, len(data), split):
        yield data[offset : offset + split]


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("split", [1, 2, 7, 65536])
async def test_both_orders_and_incremental_splits(reverse: bool, split: int) -> None:
    parts = [(FILE, b"hello"), (FIELD, FOLDER)]
    sink = BytesIO()
    result = await parse_upload(
        chunks(body(parts[::-1] if reverse else parts), split),
        "multipart/form-data; boundary=test",
        sink,
        allow_folder=True,
    )
    assert (result.filename, result.media_type, result.size, result.folder_id) == (
        "sample.txt",
        "text/plain",
        5,
        UUID(FOLDER.decode()),
    )
    assert sink.getvalue() == b"hello"


@pytest.mark.parametrize(
    "suffix", [b"extra", b"\r\nextra", b"\r", b"\n", b"\r\n\r\n", b"extra\r\n--test--"]
)
async def test_rejects_epilogue_at_every_split(suffix: bytes) -> None:
    data = body([(FILE, b"hello")])[:-2] + suffix
    for split in range(1, len(data) + 1):
        with pytest.raises(AppError):
            await parse_upload(
                chunks(data, split),
                "multipart/form-data; boundary=test",
                BytesIO(),
                allow_folder=True,
            )


@pytest.mark.parametrize(
    "parts",
    [
        [],
        [(FILE, b"")],
        [(FILE, b"a"), (FILE, b"b")],
        [(FIELD, FOLDER)],
        [(FILE, b"a"), (FIELD, FOLDER), (FIELD, FOLDER)],
        [(FILE.replace(b'"file"', b'"unknown"'), b"a")],
        [(FILE + b"\r\nContent-Transfer-Encoding: base64", b"a")],
        [(FILE + b"\r\nContent-Type: text/plain", b"a")],
        [(FILE.replace(b"form-data", b"attachment"), b"a")],
    ],
)
async def test_rejects_invalid_parts(parts: list[tuple[bytes, bytes]]) -> None:
    with pytest.raises(AppError):
        await parse_upload(
            chunks(body(parts), 1),
            "multipart/form-data; boundary=test",
            BytesIO(),
            allow_folder=True,
        )


async def test_rejects_every_truncation() -> None:
    data = body([(FILE, b"hello")])[:-2]
    for end in range(len(data)):
        with pytest.raises(AppError):
            await parse_upload(
                chunks(data[:end]),
                "multipart/form-data; boundary=test",
                BytesIO(),
                allow_folder=True,
            )


async def test_actual_payload_limit() -> None:
    for size in [3, 4]:
        sink = BytesIO()
        if size == 3:
            result = await parse_upload(
                chunks(body([(FILE, b"x" * size)])),
                "multipart/form-data; boundary=test",
                sink,
                allow_folder=False,
                policy=UploadMultipartPolicy(max_file_bytes=3),
            )
            assert result.size == 3
        else:
            with pytest.raises(AppError) as error:
                await parse_upload(
                    chunks(body([(FILE, b"x" * size)])),
                    "multipart/form-data; boundary=test",
                    sink,
                    allow_folder=False,
                    policy=UploadMultipartPolicy(max_file_bytes=3),
                )
            assert error.value.status_code == 413
            assert len(sink.getvalue()) <= 3


@pytest.mark.parametrize("terminal", [b"", b"\r\n"])
async def test_valid_terminal_every_split(terminal: bytes) -> None:
    data = body([(FILE, b"hello\r\n--testXboundary-like")])[:-2] + terminal
    for split in range(1, len(data) + 1):
        sink = BytesIO()
        await parse_upload(
            chunks(data, split), "multipart/form-data; boundary=test", sink, allow_folder=False
        )
        assert sink.getvalue() == b"hello\r\n--testXboundary-like"


@pytest.mark.parametrize("boundary_size", [256, 257])
async def test_boundary_budget(boundary_size: int) -> None:
    boundary = b"b" * boundary_size
    request = parse_upload(
        chunks(body([(FILE, b"hello")], boundary)),
        "multipart/form-data; boundary=" + boundary.decode(),
        BytesIO(),
        allow_folder=False,
    )
    if boundary_size == 256:
        assert (await request).size == 5
    else:
        with pytest.raises(AppError):
            await request


@pytest.mark.parametrize("extra", [0, 1])
async def test_raw_header_budget_includes_ignored_whitespace(extra: int) -> None:
    # 4224 includes both header line CRLF and the final empty line.
    headers = FILE.replace(
        b": form-data", b":" + b" " * (4224 - len(FILE) - 4 + 1 + extra) + b"form-data"
    )
    assert len(headers) + 4 == 4224 + extra
    request = parse_upload(
        chunks(body([(headers, b"hello")]), 65536),
        "multipart/form-data; boundary=test",
        BytesIO(),
        allow_folder=False,
    )
    if extra:
        with pytest.raises(AppError) as error:
            await request
        assert error.value.status_code == 413
    else:
        assert (await request).size == 5


async def test_field_budget_and_version_rejection() -> None:
    for field in [b"x" * 128, b"x" * 129]:
        with pytest.raises(AppError) as error:
            await parse_upload(
                chunks(body([(FILE, b"a"), (FIELD, field)]), 1),
                "multipart/form-data; boundary=test",
                BytesIO(),
                allow_folder=True,
            )
        assert error.value.status_code == (413 if len(field) == 129 else 422)
    with pytest.raises(AppError):
        await parse_upload(
            chunks(body([(FILE, b"a"), (FIELD, FOLDER)])),
            "multipart/form-data; boundary=test",
            BytesIO(),
            allow_folder=False,
        )


async def test_actual_envelope_budget() -> None:
    data = body([(FILE, b"a")])
    for allowance in [len(data) - 1, len(data) - 2]:
        request = parse_upload(
            chunks(data, 1),
            "multipart/form-data; boundary=test",
            BytesIO(),
            allow_folder=False,
            policy=UploadMultipartPolicy(max_file_bytes=1, envelope_bytes=allowance),
        )
        if allowance == len(data) - 1:
            assert (await request).size == 1
        else:
            with pytest.raises(AppError) as error:
                await request
            assert error.value.status_code == 413


@pytest.mark.parametrize(
    "content_type",
    [
        "text/plain",
        "multipart/form-data",
        "multipart/form-data; boundary=test; boundary=test",
        'multipart/form-data; boundary="test\x00"',
        "multipart/form-data; boundary=test; charset=utf-8",
    ],
)
async def test_invalid_content_type(content_type: str) -> None:
    with pytest.raises(AppError):
        await parse_upload(
            chunks(body([(FILE, b"a")])), content_type, BytesIO(), allow_folder=False
        )


@pytest.mark.parametrize(
    "header",
    [
        FILE + b"\r\nContent-Encoding: gzip",
        FILE + b"\r\nX-Secret: private-marker",
        FILE + b"\r\nContent-Disposition: form-data",
        FILE.replace(b'name="file"', b'name="file"; name="file"'),
        FILE.replace(b'filename="sample.txt"', b'filename="sample.txt"; filename="private-marker"'),
        FILE.replace(b'filename="sample.txt"', b"filename*=UTF-8''private-marker"),
        FILE.replace(b'filename="sample.txt"', b'filename="private-marker\x00"'),
        FILE.replace(b"text/plain", b'text/plain; charset="private-marker\x00"'),
        FILE.replace(b"Content-Type:", b"Content-Type\x00:"),
        FILE + b"\r\n" + b"X-A: a\r\n" * 8,
    ],
)
async def test_invalid_metadata_has_safe_error_and_no_raw_logs(
    header: bytes, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(AppError) as error:
        await parse_upload(
            chunks(body([(header, b"private-marker")])),
            "multipart/form-data; boundary=test",
            BytesIO(),
            allow_folder=False,
        )
    assert "private-marker" not in str(error.value)
    assert "private-marker" not in caplog.text
    assert not caplog.records


async def test_writes_and_parser_inputs_are_bounded() -> None:
    class Sink(BytesIO):
        def write(self, data: bytes) -> int:  # type: ignore[override]
            assert len(data) <= 65536
            return super().write(data)

    payload = b"a" * (65536 * 3 + 65000)
    sink = Sink()
    result = await parse_upload(
        chunks(body([(FILE, payload)]), 10**7),
        "multipart/form-data; boundary=test",
        sink,
        allow_folder=False,
    )
    assert result.size == len(payload)
    assert sink.getvalue() == payload


async def test_short_write_is_safe_failure() -> None:
    class Sink(BytesIO):
        def write(self, data: bytes) -> int:  # type: ignore[override]
            return len(data) - 1

    with pytest.raises(AppError) as error:
        await parse_upload(
            chunks(body([(FILE, b"hello")])),
            "multipart/form-data; boundary=test",
            Sink(),
            allow_folder=False,
        )
    assert error.value.code == "upload_write_failed"


async def test_default_50mib_limit_counts_streamed_payload() -> None:
    from ai_workshop.platform.assets.upload_policy import MAX_UPLOAD_BYTES

    class CountingSink(BytesIO):
        total = 0

        def write(self, data: bytes) -> int:  # type: ignore[override]
            assert len(data) <= 65536
            self.total += len(data)
            return len(data)

    async def large_stream(extra: int) -> AsyncIterator[bytes]:
        yield b"--test\r\n" + FILE + b"\r\n\r\n"
        for _ in range(MAX_UPLOAD_BYTES // 65536):
            yield b"a" * 65536
        yield b"a" * extra + b"\r\n--test--\r\n"

    assert MAX_UPLOAD_BYTES == 50 * 1024 * 1024
    sink = CountingSink()
    result = await parse_upload(
        large_stream(0), "multipart/form-data; boundary=test", sink, allow_folder=False
    )
    assert result.size == sink.total == MAX_UPLOAD_BYTES
    sink = CountingSink()
    with pytest.raises(AppError) as error:
        await parse_upload(
            large_stream(1), "multipart/form-data; boundary=test", sink, allow_folder=False
        )
    assert error.value.status_code == 413
    assert sink.total <= MAX_UPLOAD_BYTES


async def test_configured_header_count_limit() -> None:
    with pytest.raises(AppError):
        await parse_upload(
            chunks(body([(FILE, b"hello")])),
            "multipart/form-data; boundary=test",
            BytesIO(),
            allow_folder=False,
            policy=UploadMultipartPolicy(max_headers=1),
        )


async def test_utf8_filename_and_missing_media_type() -> None:
    header = 'Content-Disposition: form-data; name="file"; filename="문서.txt"'.encode()
    result = await parse_upload(
        chunks(body([(header, b"hello")]), 1),
        "multipart/form-data; boundary=test",
        BytesIO(),
        allow_folder=False,
    )
    assert result.filename == "문서.txt"
    assert result.media_type == "application/octet-stream"


@pytest.mark.parametrize("error_kind", [OSError, ValueError])
async def test_writer_exception_does_not_expose_private_data(
    error_kind: type[Exception], caplog: pytest.LogCaptureFixture
) -> None:
    class BrokenSink(BytesIO):
        def write(self, data: bytes) -> int:  # type: ignore[override]
            raise error_kind("private-marker")

    with pytest.raises(AppError) as error:
        await parse_upload(
            chunks(body([(FILE, b"hello")])),
            "multipart/form-data; boundary=test",
            BrokenSink(),
            allow_folder=False,
        )
    assert "private-marker" not in str(error.value)
    assert error.value.__suppress_context__
    assert not caplog.records


async def test_payload_preserved_for_boundary_prefixes_and_arbitrary_splits() -> None:
    payload = b"\r\n--tes\r\n--test-!\r\n--test\rX\r\n--testX-" * 10
    data = body([(FILE, payload), (FIELD, FOLDER)])
    for position in range(len(data) + 1):

        async def split_stream(split: int = position) -> AsyncIterator[bytes]:
            yield data[:split]
            yield b""
            yield data[split:]

        sink = BytesIO()
        result = await parse_upload(
            split_stream(), "multipart/form-data; boundary=test", sink, allow_folder=True
        )
        assert sink.getvalue() == payload
        assert result.size == len(payload)
