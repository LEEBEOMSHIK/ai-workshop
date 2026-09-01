#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from scripts import project_agents
from scripts.project_agents.contracts import (
    ActivationRule,
    RoleContract,
    WorkflowContract,
    load_activation_rules,
    load_role,
    load_workflow,
    validate_repository,
)
from scripts.project_agents.selection import (
    UnknownActivationSignalError,
    select_required_roles,
)

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

EXPECTED_PROJECT_ROLE_IDS = {
    "project-orchestrator",
    "requirements-implementation-designer",
    "system-architect",
    "frontend-engineer",
    "python-backend-engineer",
    "ai-engineer",
    "database-administrator",
    "infrastructure-docker-engineer",
    "test-designer",
    "integration-e2e-verifier",
    "security-permission-verifier",
    "data-privacy-verifier",
    "independent-code-reviewer",
    "design-adr-documentation-manager",
}

EXPECTED_RAG_ROLE_IDS = {
    "rag-lead",
    "document-structure-parser",
    "chunking-evidence-unit-specialist",
    "embedding-model-specialist",
    "indexing-specialist",
    "retrieval-fusion-specialist",
    "evidence-highlight-viewer-specialist",
    "generation-llm-specialist",
    "rag-evaluation-specialist",
}

EXPECTED_WORKFLOW_SIGNALS = {
    "feature-development": ("requirements-or-behavior", "feature-implementation"),
    "bug-fix": ("feature-implementation",),
    "architecture-change": (
        "requirements-or-behavior",
        "cross-module-or-public-contract",
        "significant-change-or-merge",
        "design-adr-or-document-structure",
    ),
    "destructive-operation": ("significant-change-or-merge",),
}

REPRESENTATIVE_SELECTION_SCENARIOS = {
    frozenset({"react-ui", "feature-implementation"}): {
        "frontend-engineer",
        "test-designer",
        "integration-e2e-verifier",
    },
    frozenset({"python-api-or-worker", "database-or-migration", "feature-implementation"}): {
        "python-backend-engineer",
        "database-administrator",
        "test-designer",
        "integration-e2e-verifier",
    },
    frozenset({"ai-model-or-runtime", "rag-behavior", "feature-implementation"}): {
        "ai-engineer",
        "rag-lead",
        "test-designer",
        "integration-e2e-verifier",
    },
    frozenset({"authentication-permission-or-exposure", "privacy-or-external-transfer"}): {
        "security-permission-verifier",
        "data-privacy-verifier",
    },
}


@pytest.fixture
def repository_root() -> Path:
    return Path(__file__).parents[2]


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    repository_root = Path(__file__).parents[2]
    with tempfile.TemporaryDirectory() as temporary_directory:
        git = Path(temporary_directory) / "git"
        git.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *rev-parse*) printf '%s\\n' true ;;\n"
            "  *) exit 0 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
        git.chmod(0o755)
        environment = os.environ.copy()
        environment["PATH"] = f"{temporary_directory}{os.pathsep}{environment['PATH']}"
        return subprocess.run(
            [sys.executable, "scripts/verify_project_agent_contracts.py", *arguments],
            cwd=repository_root,
            check=False,
            capture_output=True,
            env=environment,
            text=True,
        )


def load_repository_roles(repository_root: Path) -> tuple[RoleContract, ...]:
    role_directory = repository_root / "docs" / "project-agents" / "roles"
    return tuple(load_role(path) for path in sorted(role_directory.rglob("*.md")))


def load_repository_rag_roles(repository_root: Path) -> tuple[RoleContract, ...]:
    domain_directory = repository_root / "docs" / "project-agents" / "domains"
    return tuple(load_role(path) for path in sorted(domain_directory.rglob("*.md")))


def load_repository_workflows(repository_root: Path) -> tuple[WorkflowContract, ...]:
    workflow_directory = repository_root / "docs" / "project-agents" / "workflows"
    return tuple(load_workflow(path) for path in sorted(workflow_directory.glob("*.md")))


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


def write_activation_rules(root: Path, rules: str) -> Path:
    path = root / "docs" / "project-agents" / "governance" / "activation-rules.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nschema_version: 1\nrules:\n{rules}\n---\n\nRules explain activation.\n", encoding="utf-8")
    return path


def write_workflow(root: Path, *, workflow_id: str, default_signals: tuple[str, ...]) -> Path:
    path = root / "docs" / "project-agents" / "workflows" / f"{workflow_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    signals = "\n".join(f"  - {signal}" for signal in default_signals)
    path.write_text(
        "---\n"
        "schema_version: 1\n"
        f"workflow_id: {workflow_id}\n"
        "default_signals:\n"
        f"{signals}\n"
        "---\n\n"
        "Workflow guidance.\n",
        encoding="utf-8",
    )
    return path


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


def test_duplicate_required_heading_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    role = write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    role.write_text(
        role.read_text(encoding="utf-8").replace(
            "## 목적\n내용", "## 목적\n내용\n\n## 목적\n반복", 1
        ),
        encoding="utf-8",
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "duplicate_role_section" for issue in issues)


def test_non_orchestrator_always_activation_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(
        tmp_path,
        "roles/frontend.md",
        role_id="frontend-engineer",
        activation="always",
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "non_orchestrator_must_be_conditional" for issue in issues)


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


@pytest.mark.parametrize(
    ("role_id", "category", "scope"),
    (
        ("frontend-engineer", "engineering", "project"),
        ("document-structure-parser", "domain-specialist", "rag"),
    ),
)
def test_implementation_or_rag_specialist_missing_independent_review_relationship_is_rejected(
    tmp_path: Path,
    role_id: str,
    category: str,
    scope: str,
) -> None:
    write_minimal_repository(tmp_path)
    write_role(
        tmp_path,
        "roles/implementation.md",
        role_id=role_id,
        category=category,
        scope=scope,
        independent_from=("integration-e2e-verifier",),
    )
    write_role(tmp_path, "roles/integration.md", role_id="integration-e2e-verifier")
    write_role(tmp_path, "roles/reviewer.md", role_id="independent-code-reviewer")

    issues = validate_repository(tmp_path)

    assert any(issue.code == "missing_independent_review_relationship" for issue in issues)


@pytest.mark.parametrize(
    "role_id",
    (
        "integration-e2e-verifier",
        "independent-code-reviewer",
        "security-permission-verifier",
        "data-privacy-verifier",
    ),
)
def test_independent_verifier_or_reviewer_without_implementation_prohibition_is_rejected(
    tmp_path: Path,
    role_id: str,
) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/independent.md", role_id=role_id)

    issues = validate_repository(tmp_path)

    assert any(
        issue.code == "independent_role_missing_implementation_prohibition" for issue in issues
    )


def test_unresolved_activation_reference_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    write_activation_rules(
        tmp_path,
        "  - signal: api-change\n    required_roles: [unknown-role]",
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "unresolved_activation_reference" for issue in issues)


def test_repository_ignores_unrelated_activation_rule_documents(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    write_activation_rules(
        tmp_path,
        "  - signal: feature-implementation\n    required_roles: [backend-engineer]",
    )
    unrelated_rules = tmp_path / "unrelated" / "activation-rules.md"
    unrelated_rules.parent.mkdir()
    unrelated_rules.write_text("not a contract\n", encoding="utf-8")

    issues = validate_repository(tmp_path)

    assert not any(issue.path == unrelated_rules for issue in issues)


def test_load_activation_rules_reads_typed_frontmatter(tmp_path: Path) -> None:
    path = write_activation_rules(
        tmp_path,
        "  - signal: react-ui\n    required_roles: [frontend-engineer]",
    )

    rules = load_activation_rules(path)

    assert rules == (ActivationRule("react-ui", ("frontend-engineer",)),)


def test_load_workflow_reads_typed_frontmatter(tmp_path: Path) -> None:
    path = write_workflow(
        tmp_path,
        workflow_id="feature-development",
        default_signals=("requirements-or-behavior", "feature-implementation"),
    )

    workflow = load_workflow(path)

    assert workflow == WorkflowContract(
        "feature-development",
        ("requirements-or-behavior", "feature-implementation"),
        path,
    )


def test_package_exports_workflow_contract_interfaces() -> None:
    assert project_agents.WorkflowContract is WorkflowContract
    assert project_agents.load_workflow is load_workflow


def test_workflow_signal_must_exist_in_activation_rules(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    write_activation_rules(
        tmp_path,
        "  - signal: feature-implementation\n    required_roles: [backend-engineer]",
    )
    write_workflow(
        tmp_path,
        workflow_id="feature-development",
        default_signals=("missing-signal",),
    )

    issues = validate_repository(tmp_path)

    assert any(issue.code == "unresolved_workflow_signal" for issue in issues)


def test_duplicate_workflow_id_is_rejected(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    write_activation_rules(
        tmp_path,
        "  - signal: feature-implementation\n    required_roles: [backend-engineer]",
    )
    workflow = write_workflow(
        tmp_path,
        workflow_id="feature-development",
        default_signals=("feature-implementation",),
    )
    duplicate = workflow.with_name("feature-development-copy.md")
    duplicate.write_text(workflow.read_text(encoding="utf-8"), encoding="utf-8")

    issues = validate_repository(tmp_path)

    assert sum(issue.code == "duplicate_workflow_id" for issue in issues) == 2


def test_workflow_filename_must_match_workflow_id(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    write_activation_rules(
        tmp_path,
        "  - signal: feature-implementation\n    required_roles: [backend-engineer]",
    )
    workflow = write_workflow(
        tmp_path,
        workflow_id="feature-development",
        default_signals=("feature-implementation",),
    )
    workflow.rename(workflow.with_name("different-name.md"))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "workflow_filename_mismatch" for issue in issues)


def test_selector_unions_mandatory_roles_without_duplicates() -> None:
    rules = (
        ActivationRule("react-ui", ("frontend-engineer", "integration-e2e-verifier")),
        ActivationRule("feature-implementation", ("test-designer", "integration-e2e-verifier")),
    )

    selected = select_required_roles({"react-ui", "feature-implementation"}, rules)

    assert selected == (
        "frontend-engineer",
        "integration-e2e-verifier",
        "test-designer",
    )


@pytest.mark.parametrize(
    ("signals", "expected_roles"),
    REPRESENTATIVE_SELECTION_SCENARIOS.items(),
)
def test_representative_selection_scenarios_use_exact_mandatory_baselines(
    repository_root: Path,
    signals: frozenset[str],
    expected_roles: set[str],
) -> None:
    rules = load_activation_rules(
        repository_root / "docs" / "project-agents" / "governance" / "activation-rules.md"
    )

    assert set(select_required_roles(signals, rules)) == expected_roles


def test_documentation_only_trivial_typo_needs_no_domain_roles(
    repository_root: Path,
) -> None:
    rules = load_activation_rules(
        repository_root / "docs" / "project-agents" / "governance" / "activation-rules.md"
    )
    workflows = load_repository_workflows(repository_root)
    feature_workflow = next(
        workflow for workflow in workflows if workflow.workflow_id == "feature-development"
    )
    entry_point = (repository_root / "docs" / "project-agents" / "README.md").read_text(
        encoding="utf-8"
    )

    assert select_required_roles((), rules) == ()
    assert all("rag-behavior" not in workflow.default_signals for workflow in workflows)
    assert set(select_required_roles(feature_workflow.default_signals, rules)).isdisjoint(
        EXPECTED_RAG_ROLE_IDS
    )
    assert "사소한 오탈자" in entry_point
    assert "프로젝트 오케스트레이터 단독" in entry_point


def test_unknown_signal_is_reported() -> None:
    with pytest.raises(UnknownActivationSignalError, match="unknown-signal"):
        select_required_roles({"unknown-signal"}, ())


def test_valid_activation_rules_resolve_to_existing_roles(tmp_path: Path) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/frontend.md", role_id="frontend-engineer")
    write_role(tmp_path, "roles/verifier.md", role_id="integration-e2e-verifier")
    write_activation_rules(
        tmp_path,
        "  - signal: react-ui\n    required_roles: [frontend-engineer, integration-e2e-verifier]",
    )

    issues = validate_repository(tmp_path)

    assert not any(issue.code == "unresolved_activation_reference" for issue in issues)


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


def test_tracked_temporary_agent_work_path_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        "  *) printf '%s' '.local-data/project-agent-work/task-1/handoff.md'; printf '\\000' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "tracked_temporary_agent_work" for issue in issues)


def test_temporary_work_validator_reports_posix_path_escape_as_check_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / ".git").mkdir()
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git = executable_directory / "git"
    git.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *rev-parse*) printf '%s\\n' true ;;\n"
        "  *) printf '%s' '.local-data/project-agent-work/task-1/../../outside.txt'; printf '\\000' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "temporary_agent_work_check_failed" for issue in issues)
    assert not any(issue.code == "tracked_temporary_agent_work" for issue in issues)


def test_temporary_work_validator_does_not_report_git_output_with_windows_path_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / ".git").mkdir()
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git = executable_directory / "git"
    git.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *rev-parse*) printf '%s\\n' true ;;\n"
        "  *) printf '%s' '.local-data/project-agent-work/task-1\\\\..\\\\outside.txt'; printf '\\000' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "temporary_agent_work_check_failed" for issue in issues)
    assert not any(issue.code == "tracked_temporary_agent_work" for issue in issues)


def test_temporary_work_check_skips_non_git_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / ".git").mkdir()
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git = executable_directory / "git"
    git.write_text(
        "#!/bin/sh\nprintf '%s\\n' false\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert not any(issue.code == "temporary_agent_work_check_failed" for issue in issues)


def test_temporary_work_check_reports_when_git_repository_probe_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / ".git").mkdir()
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git = executable_directory / "git"
    git.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *rev-parse*) exit 17 ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "temporary_agent_work_check_failed" for issue in issues)


def test_temporary_work_check_reports_when_git_tracked_path_query_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / ".git").mkdir()
    executable_directory = tmp_path / "bin"
    executable_directory.mkdir()
    git = executable_directory / "git"
    git.write_text(
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *rev-parse*) printf '%s\\n' true ;;\n"
        "  *) exit 23 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_directory))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "temporary_agent_work_check_failed" for issue in issues)


def test_temporary_work_check_reports_when_git_is_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_minimal_repository(tmp_path)
    write_role(tmp_path, "roles/a.md", role_id="backend-engineer")
    (tmp_path / ".git").mkdir()
    missing_executable_directory = tmp_path / "missing-bin"
    missing_executable_directory.mkdir()
    monkeypatch.setenv("PATH", str(missing_executable_directory))

    issues = validate_repository(tmp_path)

    assert any(issue.code == "git_unavailable" for issue in issues)


def test_repository_ignores_project_agent_temporary_root(repository_root: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not available in this test image")
    result = subprocess.run(
        ["git", "check-ignore", ".local-data/project-agent-work/example/task-brief.md"],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0


def test_cache_policy_classifies_agent_work_as_temporary(repository_root: Path) -> None:
    policy = (repository_root / "CACHE_POLICY.md").read_text(encoding="utf-8")

    assert ".local-data/project-agent-work" in policy
    assert "verified" in policy


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


def test_cli_validate_returns_zero_for_repository(repository_root: Path) -> None:
    result = run_cli("validate", "--root", str(repository_root))

    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_select_prints_sorted_mandatory_roles(repository_root: Path) -> None:
    result = run_cli(
        "select",
        "--root",
        str(repository_root),
        "--signal",
        "react-ui",
        "--signal",
        "feature-implementation",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.splitlines() == [
        "frontend-engineer",
        "integration-e2e-verifier",
        "test-designer",
    ]


def test_cli_select_rejects_unknown_signal(repository_root: Path) -> None:
    result = run_cli("select", "--root", str(repository_root), "--signal", "unknown-signal")

    assert result.returncode == 2
    assert "unknown activation signal(s): unknown-signal" in result.stderr


def test_root_instructions_link_project_agent_canon_and_codex_adapter(
    repository_root: Path,
) -> None:
    agents = (repository_root / "AGENTS.md").read_text(encoding="utf-8")

    assert "docs/project-agents/README.md" in agents
    assert "docs/guidelines/codex/project-agent-orchestration.md" in agents
    assert len(agents.splitlines()) <= 200


def test_repository_contains_exact_initial_project_roles(repository_root: Path) -> None:
    roles = load_repository_roles(repository_root)
    project_ids = {role.role_id for role in roles if role.scope == "project"}

    assert project_ids == EXPECTED_PROJECT_ROLE_IDS


def test_repository_contains_exact_rag_role_catalog(repository_root: Path) -> None:
    roles = load_repository_rag_roles(repository_root)

    assert {role.role_id for role in roles} == EXPECTED_RAG_ROLE_IDS
    assert {role.scope for role in roles} == {"rag"}


def test_repository_workflows_have_expected_activation_signals(repository_root: Path) -> None:
    workflows = load_repository_workflows(repository_root)
    rules = load_activation_rules(
        repository_root / "docs" / "project-agents" / "governance" / "activation-rules.md"
    )

    assert len(workflows) == len(EXPECTED_WORKFLOW_SIGNALS)
    assert len({workflow.workflow_id for workflow in workflows}) == len(workflows)
    assert {workflow.path.stem for workflow in workflows} == set(EXPECTED_WORKFLOW_SIGNALS)
    assert {workflow.workflow_id: workflow.default_signals for workflow in workflows} == EXPECTED_WORKFLOW_SIGNALS
    assert {
        signal for workflow in workflows for signal in workflow.default_signals
    } <= {rule.signal for rule in rules}
