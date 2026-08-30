from pathlib import Path
from uuid import UUID

from ai_workshop.labs.rag.parsing.contracts import ParseRequest
from ai_workshop.labs.rag.parsing.markdown import MarkdownParser


def test_markdown_parser_preserves_heading_paths_for_repeated_visible_text(tmp_path: Path) -> None:
    source = tmp_path / "strategy.md"
    source.write_text(
        "# 투자 전략\n\n"
        "## 위험 관리\n\n"
        "동일 문구\n\n"
        "## 보고\n\n"
        "동일 문구\n",
        encoding="utf-8",
    )

    document = MarkdownParser().parse(
        ParseRequest(
            path=source,
            media_type="text/markdown",
            filename=source.name,
            asset_version_id=UUID("22222222-2222-2222-2222-222222222222"),
        )
    )

    repeated = [element for element in document.elements if element.text == "동일 문구"]
    assert [element.section_path for element in repeated] == [
        ("투자 전략", "위험 관리"),
        ("투자 전략", "보고"),
    ]
    assert [(element.location.char_start, element.location.char_end) for element in repeated] == [
        (19, 24),
        (33, 38),
    ]


def test_markdown_parser_emits_list_items_and_excludes_fenced_code_from_evidence(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scope.md"
    source.write_text(
        "# 범위\n\n"
        "설명 문단\n\n"
        "- 허용 항목\n"
        "- 두 번째 항목\n\n"
        "```python\n"
        "비공개 코드\n"
        "```\n",
        encoding="utf-8",
    )

    document = MarkdownParser().parse(
        ParseRequest(
            path=source,
            media_type="text/markdown",
            filename=source.name,
            asset_version_id=UUID("22222222-2222-2222-2222-222222222222"),
        )
    )

    assert [(element.kind, element.text) for element in document.elements] == [
        ("heading", "범위"),
        ("paragraph", "설명 문단"),
        ("list_item", "허용 항목"),
        ("list_item", "두 번째 항목"),
    ]
    assert all("비공개 코드" not in element.text for element in document.elements)
