from collections import defaultdict
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from ai_workshop.platform.assets.folder_names import folder_name_key

_ISSUE_ORDER = (
    "folder_name_noncanonical",
    "folder_name_empty",
    "folder_root_name_conflict",
    "folder_sibling_name_conflict",
    "folder_parent_workspace_mismatch",
    "document_folder_workspace_mismatch",
    "folder_cycle",
    "folder_parent_missing",
    "document_folder_missing",
)


@dataclass(frozen=True, slots=True)
class PreflightIssue:
    code: str
    entity_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class PreflightReport:
    issues: tuple[PreflightIssue, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.issues


@dataclass(frozen=True, slots=True)
class _FolderSnapshot:
    id: UUID
    workspace_id: UUID
    parent_id: UUID | None
    name: str
    active: bool


@dataclass(frozen=True, slots=True)
class _DocumentSnapshot:
    id: UUID
    workspace_id: UUID
    folder_id: UUID | None


def _load_snapshot(
    connection: Connection,
) -> tuple[tuple[_FolderSnapshot, ...], tuple[_DocumentSnapshot, ...]]:
    columns = inspect(connection).get_columns("folders")
    has_lifecycle = any(column["name"] == "lifecycle" for column in columns)
    lifecycle_column = ", lifecycle" if has_lifecycle else ""
    folder_rows = connection.execute(
        text(
            "SELECT id, workspace_id, parent_id, name"
            f"{lifecycle_column} FROM folders ORDER BY id"
        )
    ).mappings()
    folders = tuple(
        _FolderSnapshot(
            id=cast(UUID, row["id"]),
            workspace_id=cast(UUID, row["workspace_id"]),
            parent_id=cast(UUID | None, row["parent_id"]),
            name=cast(str, row["name"]),
            active=not has_lifecycle or row["lifecycle"] == "active",
        )
        for row in folder_rows
    )
    document_rows = connection.execute(
        text("SELECT id, workspace_id, folder_id FROM documents ORDER BY id")
    ).mappings()
    documents = tuple(
        _DocumentSnapshot(
            id=cast(UUID, row["id"]),
            workspace_id=cast(UUID, row["workspace_id"]),
            folder_id=cast(UUID | None, row["folder_id"]),
        )
        for row in document_rows
    )
    return folders, documents


def _cycle_ids(folders: dict[UUID, _FolderSnapshot]) -> set[UUID]:
    resolved: set[UUID] = set()
    cycles: set[UUID] = set()
    for start_id in sorted(folders):
        if start_id in resolved:
            continue
        path: list[UUID] = []
        positions: dict[UUID, int] = {}
        current_id: UUID | None = start_id
        while (
            current_id is not None
            and current_id in folders
            and current_id not in resolved
            and current_id not in positions
        ):
            positions[current_id] = len(path)
            path.append(current_id)
            current_id = folders[current_id].parent_id
        if current_id is not None and current_id in positions:
            cycles.update(path[positions[current_id] :])
        resolved.update(path)
    return cycles


def inspect_trash_migration(connection: Connection) -> PreflightReport:
    if connection.dialect.name != "postgresql":
        raise RuntimeError("asset_trash_preflight_unsupported_database")

    try:
        folders, documents = _load_snapshot(connection)
    except SQLAlchemyError:
        raise RuntimeError("asset_trash_preflight_inspection_failed") from None

    issue_ids: dict[str, set[UUID]] = defaultdict(set)
    folder_by_id = {folder.id: folder for folder in folders}
    root_names: dict[tuple[UUID, str], list[UUID]] = defaultdict(list)
    sibling_names: dict[tuple[UUID, UUID, str], list[UUID]] = defaultdict(list)

    for folder in folders:
        key = folder_name_key(folder.name)
        if key != folder.name:
            issue_ids["folder_name_noncanonical"].add(folder.id)
        if not key:
            issue_ids["folder_name_empty"].add(folder.id)
        if folder.active:
            if folder.parent_id is None:
                root_names[(folder.workspace_id, key)].append(folder.id)
            else:
                sibling_names[(folder.workspace_id, folder.parent_id, key)].append(folder.id)

        if folder.parent_id is not None:
            parent = folder_by_id.get(folder.parent_id)
            if parent is None:
                issue_ids["folder_parent_missing"].add(folder.id)
            elif parent.workspace_id != folder.workspace_id:
                issue_ids["folder_parent_workspace_mismatch"].add(folder.id)

    for entity_ids in root_names.values():
        if len(entity_ids) > 1:
            issue_ids["folder_root_name_conflict"].update(entity_ids)
    for entity_ids in sibling_names.values():
        if len(entity_ids) > 1:
            issue_ids["folder_sibling_name_conflict"].update(entity_ids)

    for document in documents:
        if document.folder_id is None:
            continue
        document_folder = folder_by_id.get(document.folder_id)
        if document_folder is None:
            issue_ids["document_folder_missing"].add(document.id)
        elif document_folder.workspace_id != document.workspace_id:
            issue_ids["document_folder_workspace_mismatch"].add(document.id)

    issue_ids["folder_cycle"].update(_cycle_ids(folder_by_id))
    issues = tuple(
        PreflightIssue(code=code, entity_ids=tuple(sorted(issue_ids[code])))
        for code in _ISSUE_ORDER
        if issue_ids[code]
    )
    return PreflightReport(issues=issues)


def assert_trash_migration_ready(connection: Connection) -> None:
    if not inspect_trash_migration(connection).ready:
        raise RuntimeError("asset_trash_preflight_failed")
