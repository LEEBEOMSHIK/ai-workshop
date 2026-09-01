#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

import yaml

ALLOWED_CATEGORIES = frozenset(
    {
        "leadership",
        "architecture",
        "engineering",
        "operations",
        "quality",
        "documentation",
        "domain-leadership",
        "domain-specialist",
    }
)
ALLOWED_SCOPES = frozenset({"project", "rag"})
ALLOWED_ACTIVATIONS = frozenset({"always", "conditional"})
REQUIRED_ROLE_HEADINGS = (
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
TEMPORARY_AGENT_WORK_ROOT = PurePosixPath(".local-data/project-agent-work")


@dataclass(frozen=True)
class RoleContract:
    role_id: str
    name: str
    category: str
    scope: str
    activation: str
    independent_from: tuple[str, ...]
    path: Path


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: Path
    message: str


class RoleContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ActivationRule:
    signal: str
    required_roles: tuple[str, ...]


@dataclass(frozen=True)
class WorkflowContract:
    workflow_id: str
    default_signals: tuple[str, ...]
    path: Path


def load_role(path: Path) -> RoleContract:
    """Load the typed YAML contract at the beginning of a role document."""
    frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    return RoleContract(
        role_id=_required_string(frontmatter, "role_id"),
        name=_required_string(frontmatter, "name"),
        category=_required_string(frontmatter, "category"),
        scope=_required_string(frontmatter, "scope"),
        activation=_required_string(frontmatter, "activation"),
        independent_from=_independent_from(frontmatter),
        path=path,
    )


def load_activation_rules(path: Path) -> tuple[ActivationRule, ...]:
    """Load typed mandatory-role rules from activation-rule document frontmatter."""
    frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    schema_version = frontmatter.get("schema_version")
    if schema_version != 1 or isinstance(schema_version, bool):
        raise RoleContractError("unsupported_activation_schema", "schema_version must be integer 1")

    raw_rules = frontmatter.get("rules")
    if not isinstance(raw_rules, list):
        raise RoleContractError("invalid_activation_rules", "rules must be a list")

    rules: list[ActivationRule] = []
    signals: set[str] = set()
    for raw_rule in raw_rules:
        if not isinstance(raw_rule, Mapping):
            raise RoleContractError("invalid_activation_rule", "each activation rule must be a mapping")
        signal = _required_string(raw_rule, "signal")
        required_roles = _required_role_ids(raw_rule)
        if signal in signals:
            raise RoleContractError("duplicate_activation_signal", f"activation signal {signal!r} is duplicated")
        signals.add(signal)
        rules.append(ActivationRule(signal, required_roles))
    return tuple(rules)


def load_workflow(path: Path) -> WorkflowContract:
    """Load the typed YAML contract at the beginning of a workflow document."""
    frontmatter, _ = _split_frontmatter(path.read_text(encoding="utf-8"))
    schema_version = frontmatter.get("schema_version")
    if schema_version != 1 or isinstance(schema_version, bool):
        raise RoleContractError("unsupported_workflow_schema", "schema_version must be integer 1")
    return WorkflowContract(
        workflow_id=_required_string(frontmatter, "workflow_id"),
        default_signals=_required_signals(frontmatter),
        path=path,
    )


def validate_repository(root: Path) -> list[ValidationIssue]:
    """Validate role documents and repository-level project-agent guardrails."""
    issues: list[ValidationIssue] = []
    roles: list[RoleContract] = []

    for role_path in _role_paths(root):
        try:
            role = load_role(role_path)
        except RoleContractError as error:
            issues.append(ValidationIssue(error.code, role_path, str(error)))
            continue
        roles.append(role)
        _, body = _split_frontmatter(role_path.read_text(encoding="utf-8"))
        issues.extend(_validate_role_body(role_path, body))
        issues.extend(_validate_role_values(role))

    issues.extend(_validate_role_references(roles))
    issues.extend(_validate_activation_references(root, roles))
    issues.extend(_validate_workflow_references(root))
    issues.extend(_validate_agents_file(root))
    issues.extend(_validate_workboard(root))
    issues.extend(_validate_tracked_temporary_paths(root))
    return issues


def _split_frontmatter(document: str) -> tuple[Mapping[str, object], str]:
    if not document.startswith("---\n"):
        raise RoleContractError("missing_frontmatter", "document must start with YAML frontmatter")
    closing_marker = document.find("\n---\n", 4)
    if closing_marker == -1:
        raise RoleContractError("invalid_frontmatter", "YAML frontmatter must have a closing delimiter")
    frontmatter_text = document[4:closing_marker]
    try:
        loaded = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError as error:
        raise RoleContractError("invalid_frontmatter", "YAML frontmatter is invalid") from error
    if not isinstance(loaded, Mapping):
        raise RoleContractError("invalid_frontmatter", "YAML frontmatter must be a mapping")
    return cast(Mapping[str, object], loaded), document[closing_marker + 5 :]


def _required_string(frontmatter: Mapping[str, object], field: str) -> str:
    value = frontmatter.get(field)
    if not isinstance(value, str) or not value.strip():
        raise RoleContractError("empty_frontmatter_value", f"{field} must be a non-empty string")
    return value.strip()


def _independent_from(frontmatter: Mapping[str, object]) -> tuple[str, ...]:
    value = frontmatter.get("independent_from")
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise RoleContractError(
            "invalid_independent_from",
            "independent_from must be a list of non-empty role IDs",
        )
    return tuple(item.strip() for item in value)


def _required_role_ids(frontmatter: Mapping[str, object]) -> tuple[str, ...]:
    value = frontmatter.get("required_roles")
    if not isinstance(value, list) or not value:
        raise RoleContractError("invalid_required_roles", "required_roles must be a non-empty list of role IDs")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RoleContractError("invalid_required_roles", "required_roles must be a non-empty list of role IDs")
    role_ids = tuple(item.strip() for item in value)
    if len(role_ids) != len(set(role_ids)):
        raise RoleContractError("duplicate_required_role", "required_roles must not contain duplicates")
    return role_ids


def _required_signals(frontmatter: Mapping[str, object]) -> tuple[str, ...]:
    value = frontmatter.get("default_signals")
    if not isinstance(value, list) or not value:
        raise RoleContractError("invalid_default_signals", "default_signals must be a non-empty list of signals")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise RoleContractError("invalid_default_signals", "default_signals must be a non-empty list of signals")
    signals = tuple(item.strip() for item in value)
    if len(signals) != len(set(signals)):
        raise RoleContractError("duplicate_default_signal", "default_signals must not contain duplicates")
    return signals


def _role_paths(root: Path) -> list[Path]:
    directories = [root / "roles", root / "docs" / "project-agents" / "roles"]
    domains_directory = root / "docs" / "project-agents" / "domains"
    if domains_directory.is_dir():
        directories.append(domains_directory)
    found: dict[Path, None] = {}
    for directory in directories:
        if directory.is_dir():
            for path in directory.rglob("*.md"):
                found[path] = None
    return sorted(found)


def _validate_role_body(path: Path, body: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for heading in REQUIRED_ROLE_HEADINGS:
        match = re.search(rf"^{re.escape(heading)}\s*$", body, re.MULTILINE)
        if match is None:
            issues.append(ValidationIssue("missing_role_section", path, f"missing required section {heading}"))
            continue
        next_heading = re.search(r"^##\s+", body[match.end() :], re.MULTILINE)
        section_end = match.end() + next_heading.start() if next_heading else len(body)
        if not body[match.end() : section_end].strip():
            issues.append(ValidationIssue("empty_role_section", path, f"required section {heading} is empty"))
    if re.search(r"\b(?:TODO|TBD)\b", body, re.IGNORECASE):
        issues.append(ValidationIssue("placeholder_text", path, "role document contains placeholder text"))
    return issues


def _validate_role_values(role: RoleContract) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for value, allowed, code, field in (
        (role.category, ALLOWED_CATEGORIES, "invalid_category", "category"),
        (role.scope, ALLOWED_SCOPES, "invalid_scope", "scope"),
        (role.activation, ALLOWED_ACTIVATIONS, "invalid_activation", "activation"),
    ):
        if value not in allowed:
            issues.append(ValidationIssue(code, role.path, f"{field} has unsupported value {value!r}"))
    return issues


def _validate_role_references(roles: Iterable[RoleContract]) -> list[ValidationIssue]:
    role_list = list(roles)
    issues: list[ValidationIssue] = []
    ids_to_roles: dict[str, list[RoleContract]] = {}
    for role in role_list:
        ids_to_roles.setdefault(role.role_id, []).append(role)
    for role_id, matching_roles in ids_to_roles.items():
        if len(matching_roles) > 1:
            for role in matching_roles:
                issues.append(ValidationIssue("duplicate_role_id", role.path, f"role_id {role_id!r} is duplicated"))
    role_ids = frozenset(ids_to_roles)
    for role in role_list:
        for reference in role.independent_from:
            if reference not in role_ids:
                issues.append(
                    ValidationIssue(
                        "unresolved_independent_from",
                        role.path,
                        f"independent_from references unknown role_id {reference!r}",
                    )
                )
    return issues


def _validate_activation_references(root: Path, roles: Iterable[RoleContract]) -> list[ValidationIssue]:
    role_ids = frozenset(role.role_id for role in roles)
    issues: list[ValidationIssue] = []
    for path in _activation_rule_paths(root):
        try:
            rules = load_activation_rules(path)
        except RoleContractError as error:
            issues.append(ValidationIssue(error.code, path, str(error)))
            continue
        for rule in rules:
            for reference in rule.required_roles:
                if reference not in role_ids:
                    issues.append(
                        ValidationIssue(
                            "unresolved_activation_reference",
                            path,
                            f"activation rule references unknown role_id {reference!r}",
                        )
                    )
    return issues


def _validate_workflow_references(root: Path) -> list[ValidationIssue]:
    known_signals: set[str] = set()
    issues: list[ValidationIssue] = []
    for activation_path in _activation_rule_paths(root):
        try:
            known_signals.update(rule.signal for rule in load_activation_rules(activation_path))
        except RoleContractError:
            continue

    workflows: list[WorkflowContract] = []
    for workflow_path in _workflow_paths(root):
        try:
            workflow = load_workflow(workflow_path)
        except RoleContractError as error:
            issues.append(ValidationIssue(error.code, workflow_path, str(error)))
            continue
        workflows.append(workflow)
        if workflow.path.stem != workflow.workflow_id:
            issues.append(
                ValidationIssue(
                    "workflow_filename_mismatch",
                    workflow.path,
                    f"workflow filename {workflow.path.stem!r} must match workflow_id {workflow.workflow_id!r}",
                )
            )
        for signal in workflow.default_signals:
            if signal not in known_signals:
                issues.append(
                    ValidationIssue(
                        "unresolved_workflow_signal",
                        workflow.path,
                        f"workflow references unknown activation signal {signal!r}",
                    )
                )

    ids_to_workflows: dict[str, list[WorkflowContract]] = {}
    for workflow in workflows:
        ids_to_workflows.setdefault(workflow.workflow_id, []).append(workflow)
    for workflow_id, matching_workflows in ids_to_workflows.items():
        if len(matching_workflows) > 1:
            for workflow in matching_workflows:
                issues.append(
                    ValidationIssue(
                        "duplicate_workflow_id",
                        workflow.path,
                        f"workflow_id {workflow_id!r} is duplicated",
                    )
                )
    return issues


def _activation_rule_paths(root: Path) -> tuple[Path, ...]:
    path = root / "docs" / "project-agents" / "governance" / "activation-rules.md"
    return (path,) if path.is_file() else ()


def _workflow_paths(root: Path) -> list[Path]:
    directory = root / "docs" / "project-agents" / "workflows"
    if not directory.is_dir():
        return []
    return sorted(directory.glob("*.md"))


def _validate_agents_file(root: Path) -> list[ValidationIssue]:
    path = root / "AGENTS.md"
    if not path.is_file():
        return []
    if len(path.read_text(encoding="utf-8").splitlines()) > 200:
        return [ValidationIssue("agents_file_too_long", path, "AGENTS.md exceeds 200 lines")]
    return []


def _validate_workboard(root: Path) -> list[ValidationIssue]:
    path = root / "WORKBOARD.md"
    if not path.is_file():
        return []
    document = path.read_text(encoding="utf-8")
    match = re.search(r"^## 최근 완료 작업\s*$([\s\S]*?)(?=^##\s|\Z)", document, re.MULTILINE)
    if match is None:
        return []
    completion_count = len(re.findall(r"^\s*\d+\.\s+", match.group(1), re.MULTILINE))
    if completion_count > 5:
        return [
            ValidationIssue(
                "too_many_recent_completions",
                path,
                "WORKBOARD.md contains more than five recent completions",
            )
        ]
    return []


def _validate_tracked_temporary_paths(root: Path) -> list[ValidationIssue]:
    try:
        is_repository, repository_issue = _is_git_repository(root)
        if repository_issue is not None:
            return [repository_issue]
        if not is_repository:
            return []
        result = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "-z",
                "--",
                f"{TEMPORARY_AGENT_WORK_ROOT}/",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [
            ValidationIssue(
                "git_unavailable",
                root,
                "git executable is unavailable; cannot verify tracked temporary project-agent work",
            )
        ]
    if result.returncode != 0:
        return [_temporary_agent_work_check_failure(root, "git ls-files")]
    issues: list[ValidationIssue] = []
    for raw_path in result.stdout.split("\0"):
        if not raw_path:
            continue
        if "\\" in raw_path:
            issues.append(_temporary_agent_work_check_failure(root, "git ls-files path validation"))
            continue
        relative_path = _temporary_agent_work_path(raw_path)
        if relative_path is not None:
            issues.append(
                ValidationIssue(
                    "tracked_temporary_agent_work",
                    root.joinpath(*relative_path.parts),
                    "temporary project-agent work must not be tracked",
                )
            )
    return issues


def _temporary_agent_work_path(raw_path: str) -> PurePosixPath | None:
    if "\\" in raw_path:
        return None
    relative_path = PurePosixPath(raw_path)
    if (
        relative_path.is_absolute()
        or len(relative_path.parts) < 3
        or relative_path.parts[:2] != TEMPORARY_AGENT_WORK_ROOT.parts
        or any(part in {".", ".."} for part in relative_path.parts)
    ):
        return None
    return relative_path


def _temporary_agent_work_check_failure(root: Path, operation: str) -> ValidationIssue:
    return ValidationIssue(
        "temporary_agent_work_check_failed",
        root,
        f"{operation} failed; cannot safely verify tracked temporary project-agent work",
    )


def _is_git_repository(root: Path) -> tuple[bool, ValidationIssue | None]:
    if not (root / ".git").exists():
        return False, None
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return False, ValidationIssue(
            "git_unavailable",
            root,
            "git executable is unavailable; cannot verify tracked temporary project-agent work",
        )
    if result.returncode != 0:
        return False, _temporary_agent_work_check_failure(root, "git rev-parse")
    if result.stdout.strip() == "true":
        return True, None
    if result.stdout.strip() == "false":
        return False, None
    return False, _temporary_agent_work_check_failure(root, "git rev-parse")
