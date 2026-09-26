import json
from pathlib import Path

import pytest

from ai_workshop.platform.issue_history.importer import prepare_import


def source(root: Path) -> Path:
    (root / "docs/issues").mkdir(parents=True)
    (root / "docs/worklogs").mkdir()
    (root / "docs/worklogs/example.md").write_text(
        "# Synthetic evidence\n", encoding="utf8", newline="\n"
    )
    path = root / "docs/issues/issues.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "visibility": "internal",
                "updated_at": "2026-09-27",
                "issues": [
                    {
                        "id": "TEST-1",
                        "title": "Synthetic",
                        "area": "attachments",
                        "status": "open",
                        "symptom": "symptom",
                        "cause": "cause",
                        "resolution": "pending",
                        "verification": [],
                        "remaining": ["verify"],
                        "commits": [],
                        "history": [{"date": "2026-09-27", "event": "reported"}],
                        "evidence": ["docs/worklogs/example.md"],
                    }
                ],
            }
        ),
        encoding="utf8",
    )
    return path


def test_manifest_preserves_history_and_deduplicates_documents(tmp_path: Path) -> None:
    path = source(tmp_path)
    first = prepare_import(tmp_path)
    second = prepare_import(tmp_path)
    assert first.digest == second.digest
    assert first.documents[0].content == "# Synthetic evidence\n"
    assert first.issues[0].history[0].event == "reported"
    value = json.loads(path.read_text())
    value["issues"].append({**value["issues"][0], "id": "TEST-2"})
    path.write_text(json.dumps(value), encoding="utf8")
    assert len(prepare_import(tmp_path).documents) == 1


def test_changed_content_changes_manifest(tmp_path: Path) -> None:
    source(tmp_path)
    original = prepare_import(tmp_path).digest
    (tmp_path / "docs/worklogs/example.md").write_text("# Revised", encoding="utf8")
    assert prepare_import(tmp_path).digest != original


@pytest.mark.parametrize(
    "name", ["../secret.md", "docs/../secret.md", "docs/issues/issues.json", "C:/secret.md"]
)
def test_rejects_unapproved_paths(tmp_path: Path, name: str) -> None:
    path = source(tmp_path)
    value = json.loads(path.read_text())
    value["issues"][0]["evidence"] = [name]
    path.write_text(json.dumps(value), encoding="utf8")
    with pytest.raises(ValueError):
        prepare_import(tmp_path)


def test_rejects_duplicates_missing_invalid_utf8_and_oversize(tmp_path: Path) -> None:
    path = source(tmp_path)
    value = json.loads(path.read_text())
    value["issues"].append(value["issues"][0])
    path.write_text(json.dumps(value), encoding="utf8")
    with pytest.raises(ValueError):
        prepare_import(tmp_path)
    value["issues"].pop()
    path.write_text(json.dumps(value), encoding="utf8")
    document = tmp_path / "docs/worklogs/example.md"
    for content in (b"\xff", b"a" * (512 * 1024 + 1)):
        document.write_bytes(content)
        with pytest.raises(ValueError):
            prepare_import(tmp_path)
    document.unlink()
    with pytest.raises(ValueError):
        prepare_import(tmp_path)
