#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.project_agents.contracts import load_role, validate_repository

REQUIRED_HEADINGS = (
    "## 목적",
    "## 담당 범위",
    "## 호출 조건",
    "## 비호출 조건",
    "## 작업 전 필수 문서",
    "## 필수 입력",
    "## 책임",
    "## 권한",
    "## 금지 사항",
    "## 산출물",
    "## 인계",
    "## 설정·하드코딩 점검",
    "## 필수 검증",
    "## 완료 조건",
    "## 중단·에스컬레이션",
)


def write_minimal_repository(root: Path) -> None:
    (root / "roles").mkdir()
    (root / "AGENTS.md").write_text("# Instructions\n", encoding="utf-8")
    (root / "WORKBOARD.md").write_text("## 최근 완료 작업\n\n", encoding="utf-8")


def write_role(
    root: Path,
    relative_path: str,
    *,
    role_id: str,
    category: str = "engineering",
    scope: str = "project",
    activation: str = "conditional",
    independent_from: tuple[str, ...] = (),
) -> Path:
    role_path = root / relative_path
    role_path.parent.mkdir(parents=True, exist_ok=True)
    dependencies = "\n".join(f"  - {value}" for value in independent_from)
    role_path.write_text(
        "---\n"
        f"role_id: {role_id}\n"
        f"name: {role_id} name\n"
        f"category: {category}\n"
        f"scope: {scope}\n"
        f"activation: {activation}\n"
        "independent_from:\n"
        f"{dependencies}\n"
        "---\n\n"
        f"{'\n'.join(f'{heading}\n내용' for heading in REQUIRED_HEADINGS)}\n",
        encoding="utf-8",
    )
    return role_path


def test_load_role_reads_valid_frontmatter(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    role_path = write_role(
        tmp_path,
        "roles/backend.md",
        role_id="backend-engineer",
        independent_from=("integration-verifier",),
    )

    role = load_role(role_path)

    assert role.role_id == "backend-engineer"
    assert role.independent_from == ("integration-verifier",)
    assert role.path == role_path


def test_missing_frontmatter_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    (tmp_path / "roles" / "missing.md").write_text("# No metadata\n", encoding="utf-8")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "missing_frontmatter" for issue in issues)


def test_duplicate_role_ids_are_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="duplicate")
    write_role(tmp_path, "roles/b.md", role_id="duplicate")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "duplicate_role_id" for issue in issues)


def test_invalid_category_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer", category="unsupported")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "invalid_category" for issue in issues)


def test_invalid_scope_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer", scope="unsupported")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "invalid_scope" for issue in issues)


def test_invalid_activation_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer", activation="unsupported")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "invalid_activation" for issue in issues)


def test_missing_required_heading_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    role = write_role(tmp_path, "roles/a.md", role_id="frontend-engineer")
    role.write_text(
        role.read_text(encoding="utf-8").replace("## 필수 검증\n", ""),
        encoding="utf-8",
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "missing_role_section" for issue in issues)


def test_unresolved_independent_role_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(
        tmp_path,
        "roles/a.md",
        role_id="backend-engineer",
        independent_from=("unknown-verifier",),
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "unresolved_independent_from" for issue in issues)


def test_unresolved_activation_reference_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / "activation-rules.md").write_text(
        "# Activation rules\n\n- `unknown-role`\n",
        encoding="utf-8",
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "unresolved_activation_reference" for issue in issues)


def test_agents_file_over_200_lines_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / "AGENTS.md").write_text("line\n" * 201, encoding="utf-8")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "agents_file_too_long" for issue in issues)


def test_more_than_five_recent_completions_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    completions = "\n".join(f"{number}. completed" for number in range(1, 7))
    (tmp_path / "WORKBOARD.md").write_text(
        f"## 최근 완료 작업\n\n{completions}\n\n## 다음 작업\n",
        encoding="utf-8",
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "too_many_recent_completions" for issue in issues)


def test_tracked_temporary_work_path_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    temporary_path = tmp_path / ".local-data" / "project-agent-work" / "task-1" / "handoff.md"
    temporary_path.parent.mkdir(parents=True)
    temporary_path.write_text("temporary\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git = executable_directory / "git"
    git.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *rev-parse*) printf '%s\\n' true ;;\n"
        "  *) printf '%s\\n' '.local-data/project-agent-work/task-1/handoff.md' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "tracked_temporary_work_path" for issue in issues)


def test_temporary_work_check_skips_non_git_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / ".git").mkdir()
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git = executable_directory / "git"
    git.write_text(
        "#!/bin/sh\nprintf '%s\\n' '.local-data/project-agent-work/task-1/handoff.md'\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert not any(issue.code == "tracked_temporary_work_path" for issue in issues)


def test_placeholder_text_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    role = write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    role.write_text(role.read_text(encoding="utf-8").replace("내용", "TODO", 1), encoding="utf-8")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "placeholder_text" for issue in issues)


def test_validate_cli_reports_issues_and_exit_status(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    (tmp_path / "roles" / "missing.md").write_text("# No metadata\n", encoding="utf-8")
    repository_root = Path(__file__).parents[2]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_project_agent_contracts.py",
            "validate",
            "--root",
            str(tmp_path),
        ],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "missing_frontmatter" in result.stdout
