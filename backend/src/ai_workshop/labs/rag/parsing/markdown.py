import re
from uuid import uuid4

from ai_workshop.labs.rag.documents.domain import ParsedDocument, SourceLocation, StructuralElement
from ai_workshop.labs.rag.parsing.contracts import ParseRequest, UnsupportedEncodingError


class MarkdownParser:
    media_types = frozenset({"text/markdown", "text/x-markdown"})
    suffixes = frozenset({".md", ".markdown"})
    parser_name = "markdown"
    parser_version = "1"

    def parse(self, request: ParseRequest) -> ParsedDocument:
        try:
            text = request.path.read_bytes().decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise UnsupportedEncodingError() from error
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        elements: list[StructuralElement] = []
        section_stack: list[tuple[int, str]] = []
        in_fence = False
        paragraph_start: int | None = None
        paragraph_end: int | None = None
        paragraph_lines: list[str] = []

        def current_path() -> tuple[str, ...]:
            return tuple(title for _, title in section_stack)

        def append_element(
            *,
            kind: str,
            value: str,
            char_start: int,
            char_end: int,
            section_path: tuple[str, ...],
        ) -> None:
            element_id = uuid4()
            elements.append(
                StructuralElement(
                    id=element_id,
                    ordinal=len(elements),
                    kind=kind,
                    text=value,
                    section_path=section_path,
                    location=SourceLocation(
                        element_id=element_id,
                        page=None,
                        char_start=char_start,
                        char_end=char_end,
                        bbox=None,
                    ),
                    parser_name=self.parser_name,
                    parser_version=self.parser_version,
                    confidence=1.0,
                )
            )

        def flush_paragraph() -> None:
            nonlocal paragraph_start, paragraph_end, paragraph_lines
            if paragraph_start is not None and paragraph_end is not None:
                append_element(
                    kind="paragraph",
                    value="\n".join(paragraph_lines),
                    char_start=paragraph_start,
                    char_end=paragraph_end,
                    section_path=current_path(),
                )
            paragraph_start = None
            paragraph_end = None
            paragraph_lines = []

        offset = 0
        for line in normalized.splitlines(keepends=True):
            content = line.rstrip("\n")
            fence = re.match(r"^\s*(`{3,}|~{3,})", content)
            if fence is not None:
                flush_paragraph()
                in_fence = not in_fence
                offset += len(line)
                continue
            if in_fence:
                offset += len(line)
                continue
            heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", content)
            if heading is not None:
                flush_paragraph()
                level = len(heading.group(1))
                title = heading.group(2).strip()
                heading_text = heading.group(2)
                title_start = offset + heading.start(2) + len(heading_text) - len(
                    heading_text.lstrip()
                )
                section_stack[:] = [item for item in section_stack if item[0] < level]
                section_stack.append((level, title))
                append_element(
                    kind="heading",
                    value=title,
                    char_start=title_start,
                    char_end=title_start + len(title),
                    section_path=current_path(),
                )
                offset += len(line)
                continue
            list_item = re.match(r"^\s*[-*+]\s+(.*?)(?:\s*)$", content)
            if list_item is not None:
                flush_paragraph()
                value = list_item.group(1).strip()
                value_start = offset + list_item.start(1) + (
                    len(list_item.group(1)) - len(list_item.group(1).lstrip())
                )
                append_element(
                    kind="list_item",
                    value=value,
                    char_start=value_start,
                    char_end=value_start + len(value),
                    section_path=current_path(),
                )
                offset += len(line)
                continue
            if content.strip():
                leading = len(content) - len(content.lstrip())
                if paragraph_start is None:
                    paragraph_start = offset + leading
                paragraph_end = offset + len(content.rstrip())
                paragraph_lines.append(content.strip())
            else:
                flush_paragraph()
            offset += len(line)
        flush_paragraph()
        return ParsedDocument(
            asset_version_id=request.asset_version_id,
            parser_name=self.parser_name,
            parser_version=self.parser_version,
            elements=tuple(elements),
        )
