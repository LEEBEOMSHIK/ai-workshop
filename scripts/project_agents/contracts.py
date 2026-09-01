#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
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
    issues.extend(_validate_agents_file(root))
    issues.extend(_validate_workboard(root))
    issues.extend(_validate_tracked_temporary_paths(root))
    return issues


def _split_frontmatter(document: str) -> tuple[Mapping[str, object], str]:
    if not document.startswith("---\n"):
        raise RoleContractError("missing_frontmatter", "role document must start with YAML frontmatter")
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
    for path in root.rglob("activation-rules.md"):
        for reference in _activation_references(path.read_text(encoding="utf-8")):
            if reference not in role_ids:
                issues.append(
                    ValidationIssue(
                        "unresolved_activation_reference",
                        path,
                        f"activation rule references unknown role_id {reference!r}",
                    )
                )
    return issues


def _activation_references(document: str) -> set[str]:
    references = set(re.findall(r"`([a-z0-9]+(?:-[a-z0-9]+)+)`", document))
    references.update(re.findall(r"^\s*-\s*([a-z0-9]+(?:-[a-z0-9]+)+)\s*$", document, re.MULTILINE))
    return references


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
    if not _is_git_repository(root):
        return []
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--", ".local-data/project-agent-work"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [
        ValidationIssue("tracked_temporary_work_path", root / relative_path, "temporary project-agent work must not be tracked")
        for relative_path in result.stdout.splitlines()
    ]


def _is_git_repository(root: Path) -> bool:
    if not (root / ".git").exists():
        return False
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"
