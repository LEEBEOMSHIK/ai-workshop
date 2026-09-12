from __future__ import annotations

import json
import sys
from pathlib import Path

from ai_workshop.infrastructure.document_formats.pdf_preview import (
    PdfInvalidError,
    PdfPageError,
    PdfPreviewLimitError,
    inspect_pdf_bytes,
    render_pdf_page_bytes,
)

_EXIT_INVALID = 20
_EXIT_LIMIT = 21
_EXIT_PAGE = 22
_EXIT_FAILURE = 23


def main(arguments: list[str]) -> int:
    if len(arguments) not in {8, 9}:
        return _EXIT_FAILURE
    operation, raw_input, raw_output, raw_metadata = arguments[:4]
    if operation not in {"inspect", "render"}:
        return _EXIT_FAILURE
    try:
        input_limit = _positive_int(arguments[4])
        max_pages = _positive_int(arguments[5])
        max_pixels = _positive_int(arguments[6])
        output_limit = _positive_int(arguments[7])
        page_number = _positive_int(arguments[8]) if operation == "render" else None
        input_path = Path(raw_input)
        output_path = Path(raw_output)
        metadata_path = Path(raw_metadata)
        with input_path.open("rb") as source:
            content = source.read(input_limit + 1)
        if len(content) > input_limit:
            raise PdfPreviewLimitError
        inspection = inspect_pdf_bytes(content, max_pages=max_pages)
        metadata: dict[str, int] = {"page_count": inspection.page_count}
        if operation == "render":
            assert page_number is not None
            rendered = render_pdf_page_bytes(
                content,
                page_number,
                max_pixels=max_pixels,
            )
            if len(rendered) > output_limit:
                raise PdfPreviewLimitError
            output_path.write_bytes(rendered)
            metadata["output_size"] = len(rendered)
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=True, separators=(",", ":")),
            encoding="ascii",
        )
        return 0
    except PdfInvalidError:
        return _EXIT_INVALID
    except PdfPreviewLimitError:
        return _EXIT_LIMIT
    except PdfPageError:
        return _EXIT_PAGE
    except (AssertionError, OSError, TypeError, ValueError):
        return _EXIT_FAILURE


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise ValueError
    return parsed


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
