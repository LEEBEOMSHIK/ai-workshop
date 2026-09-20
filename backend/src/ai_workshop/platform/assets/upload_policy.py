"""Shared payload and HTTP multipart resource budgets."""

from dataclasses import dataclass

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class UploadMultipartPolicy:
    max_file_bytes: int = MAX_UPLOAD_BYTES
    envelope_bytes: int = 64 * 1024
    slice_bytes: int = 64 * 1024
    max_boundary_bytes: int = 256
    max_headers: int = 8
    max_header_bytes: int = 4224
    max_field_bytes: int = 128

    def __post_init__(self) -> None:
        for value in (
            self.max_file_bytes,
            self.envelope_bytes,
            self.slice_bytes,
            self.max_boundary_bytes,
            self.max_headers,
            self.max_header_bytes,
            self.max_field_bytes,
        ):
            if type(value) is not int or value < 1:
                raise ValueError("Upload budgets must be positive integers.")


DEFAULT_POLICY = UploadMultipartPolicy()
