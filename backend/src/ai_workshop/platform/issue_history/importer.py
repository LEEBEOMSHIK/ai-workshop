"""Explicit, all-or-nothing import of the repository's historical issue ledger."""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_BYTES = 512 * 1024
CATEGORY_NAMES = {
    "conversation-lifecycle": "대화 수명주기",
    "attachments": "파일 첨부",
    "conversation-ui": "대화 화면",
    "document-selection": "문서 선택",
    "retrieval-evidence": "검색·근거",
    "conversation-readiness": "대화 준비",
    "request-transport": "요청 처리",
    "local-environment": "로컬 실행 환경",
}
ROOT_CATEGORY_NAMES = {"rag": "RAG", "platform": "공통 플랫폼"}
CATEGORY_PARENTS = {
    "conversation-lifecycle": "rag",
    "attachments": "rag",
    "conversation-ui": "rag",
    "document-selection": "rag",
    "retrieval-evidence": "rag",
    "conversation-readiness": "rag",
    "request-transport": "platform",
    "local-environment": "platform",
}


def category_parent_code(code: str) -> str:
    if code not in CATEGORY_PARENTS:
        raise ValueError("An import category requires an explicit technology parent.")
    return CATEGORY_PARENTS[code]


ShortText = Annotated[str, Field(max_length=2000)]
TextList = Annotated[list[ShortText], Field(max_length=100)]


class SourceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date: date
    event: str = Field(min_length=1, max_length=20_000)


class SourceIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=200)
    area: str = Field(min_length=1, max_length=80)
    status: Literal["open", "implemented", "verified"]
    symptom: str = Field(max_length=20_000)
    cause: str = Field(max_length=20_000)
    resolution: str = Field(max_length=20_000)
    verification: TextList
    remaining: TextList
    commits: TextList
    history: list[SourceEvent] = Field(max_length=1000)
    evidence: TextList


class SourceLedger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    visibility: Literal["internal"]
    updated_at: date
    issues: list[SourceIssue] = Field(min_length=1, max_length=1000)


@dataclass(frozen=True)
class ImportDocument:
    path: str
    content: str
    sha256: str


@dataclass(frozen=True)
class ImportManifest:
    digest: str
    issues: tuple[SourceIssue, ...]
    documents: tuple[ImportDocument, ...]

    def summary(self) -> dict[str, int | str]:
        return {
            "manifest_hash": self.digest,
            "issues": len(self.issues),
            "categories": len({issue.area for issue in self.issues}),
            "documents": len(self.documents),
            "events": sum(len(issue.history) for issue in self.issues),
            "links": sum(len(issue.evidence) for issue in self.issues),
        }


def _read(root: Path, relative: str) -> bytes:
    target = root / relative
    try:
        if target.resolve(strict=True) != target or not target.is_file():
            raise ValueError("Import source must be a regular, non-linked repository file.")
        with target.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise ValueError("Import source exceeds the size limit.")
        content.decode("utf8")
        return content
    except (OSError, UnicodeError) as exc:
        raise ValueError("Import source is missing or is not UTF-8.") from exc


def prepare_import(root: Path) -> ImportManifest:
    root = root.resolve(strict=True)
    raw = _read(root, "docs/issues/issues.json")
    try:
        ledger = SourceLedger.model_validate_json(raw)
    except ValidationError as exc:
        raise ValueError("The issue ledger does not match the import contract.") from exc
    if len({issue.id for issue in ledger.issues}) != len(ledger.issues):
        raise ValueError("Duplicate issue IDs.")
    documents: dict[str, ImportDocument] = {}
    for issue in ledger.issues:
        if issue.area not in CATEGORY_NAMES:
            raise ValueError("An import category requires an explicit Korean label.")
        category_parent_code(issue.area)
        if len(set(issue.evidence)) != len(issue.evidence):
            raise ValueError("Duplicate document links.")
        for name in issue.evidence:
            if name != "WORKBOARD.md" and not re.fullmatch(r"docs/[A-Za-z0-9_./-]+\.md", name):
                raise ValueError("Document path is not an approved Markdown source.")
            if any(part in (".", "..", "") for part in name.split("/")):
                raise ValueError("Document path is not canonical.")
            if name not in documents:
                content = _read(root, name)
                documents[name] = ImportDocument(
                    name, content.decode("utf8"), hashlib.sha256(content).hexdigest()
                )
    manifest_bytes = json.dumps(
        {
            "ledger": ledger.model_dump(mode="json"),
            "documents": {name: doc.sha256 for name, doc in sorted(documents.items())},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf8")
    return ImportManifest(
        hashlib.sha256(manifest_bytes).hexdigest(),
        tuple(ledger.issues),
        tuple(documents[name] for name in sorted(documents)),
    )


def import_id(source_key: str, kind: str, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"ai-workshop:issue-history:{source_key}:{kind}:{key}")


async def apply_import(
    session: "AsyncSession",
    manifest: ImportManifest,
    actor_id: UUID,
    source_key: str = "repository-issue-ledger-v1",
) -> dict[str, int | str]:
    from sqlalchemy.exc import IntegrityError

    from ai_workshop.shared.errors import AppError

    try:
        return await _apply_import(session, manifest, actor_id, source_key)
    except IntegrityError as exc:
        # Caller must roll back the transaction. Never expose SQL parameter contents.
        raise AppError(
            "issue_import_conflict", "Import conflicts with existing data.", 409
        ) from exc


async def _apply_import(
    session: "AsyncSession",
    manifest: ImportManifest,
    actor_id: UUID,
    source_key: str = "repository-issue-ledger-v1",
) -> dict[str, int | str]:
    """Caller owns transaction; no commit or filesystem reads happen here."""
    from sqlalchemy import select, text

    from ai_workshop.platform.identity.models import UserRecord
    from ai_workshop.platform.issue_history.models import (
        Issue,
        IssueCategory,
        IssueDocument,
        IssueDocumentLink,
        IssueDocumentVersion,
        IssueEvent,
        IssueImportRun,
    )
    from ai_workshop.shared.errors import AppError

    actor = await session.get(UserRecord, actor_id)
    if actor is None or not actor.is_active or actor.role != "owner":
        raise AppError("owner_required", "Owner access is required.", 403)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "issue-history-category-hierarchy"},
    )
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": "issue-history-import:" + source_key},
    )
    previous = await session.get(IssueImportRun, source_key)
    if previous:
        if previous.manifest_hash != manifest.digest:
            raise AppError(
                "issue_import_conflict", "Import source has changed; use the management API.", 409
            )
        return {**manifest.summary(), "result": "unchanged"}
    for model, column, keys in (
        (Issue, Issue.issue_key, [item.id for item in manifest.issues]),
        (IssueCategory, IssueCategory.code, list({item.area for item in manifest.issues})),
        (
            IssueDocument,
            IssueDocument.import_source_key,
            [item.path for item in manifest.documents],
        ),
    ):
        if await session.scalar(select(model).where(column.in_(keys)).limit(1)):
            raise AppError("issue_import_conflict", "Import identifiers already exist.", 409)
    categories = {
        code: import_id(source_key, "category", code)
        for code in sorted({item.area for item in manifest.issues})
    }
    roots: dict[str, UUID] = {}
    for root_code in sorted({category_parent_code(code) for code in categories}):
        existing_root = await session.scalar(
            select(IssueCategory).where(IssueCategory.code == root_code)
        )
        if existing_root is None:
            existing_root = IssueCategory(
                id=import_id(source_key, "root-category", root_code),
                code=root_code,
                name=ROOT_CATEGORY_NAMES[root_code],
                sort_order=list(ROOT_CATEGORY_NAMES).index(root_code),
                is_active=True,
                revision=1,
                parent_id=None,
            )
            session.add(existing_root)
            await session.flush()
        if existing_root.parent_id is not None or not existing_root.is_active:
            raise AppError("issue_import_conflict", "Import parent is not an active root.", 409)
        roots[root_code] = existing_root.id
    for order, (code, category_id) in enumerate(categories.items()):
        session.add(
            IssueCategory(
                id=category_id,
                code=code,
                name=CATEGORY_NAMES[code],
                sort_order=order,
                is_active=True,
                revision=1,
                parent_id=roots[category_parent_code(code)],
            )
        )
    await session.flush()
    document_ids: dict[str, UUID] = {}
    for doc in manifest.documents:
        document_id = import_id(source_key, "document", doc.path)
        document_ids[doc.path] = document_id
        title = next(
            (line[2:].strip() for line in doc.content.splitlines() if line.startswith("# ")),
            Path(doc.path).stem,
        )
        session.add(
            IssueDocument(
                id=document_id,
                title=title[:200],
                import_source_key=doc.path,
                current_version=1,
                revision=1,
            )
        )
        await session.flush()
        session.add(
            IssueDocumentVersion(
                document_id=document_id,
                version=1,
                content=doc.content,
                sha256=doc.sha256,
                source_path=doc.path,
                actor_id=actor_id,
            )
        )
    await session.flush()
    for original in manifest.issues:
        issue_id = import_id(source_key, "issue", original.id)
        values = original.model_dump(exclude={"id", "area", "history", "evidence"})
        session.add(
            Issue(
                id=issue_id,
                issue_key=original.id,
                category_id=categories[original.area],
                revision=1,
                **values,
            )
        )
        await session.flush()
        for index, event in enumerate(original.history):
            session.add(
                IssueEvent(
                    id=import_id(source_key, "event", f"{original.id}:{index}"),
                    issue_id=issue_id,
                    event_date=event.date,
                    actor_id=actor_id,
                    kind="imported",
                    description=event.event,
                    before_revision=None,
                    after_revision=1,
                    snapshot={"source": "repository", "sequence": index},
                )
            )
        for order, name in enumerate(original.evidence):
            session.add(
                IssueDocumentLink(
                    issue_id=issue_id, document_id=document_ids[name], version=1, sort_order=order
                )
            )
    session.add(
        IssueImportRun(
            source_key=source_key,
            manifest_hash=manifest.digest,
            actor_id=actor_id,
            summary=manifest.summary(),
        )
    )
    await session.flush()
    return {**manifest.summary(), "result": "imported"}


async def verify_import(
    session: "AsyncSession",
    manifest: ImportManifest,
    source_key: str = "repository-issue-ledger-v1",
) -> dict[str, int | str]:
    """Initial cutover audit; compare private content without printing it."""
    from sqlalchemy import select

    from ai_workshop.platform.issue_history.models import (
        Issue,
        IssueCategory,
        IssueDocument,
        IssueDocumentLink,
        IssueDocumentVersion,
        IssueEvent,
        IssueImportRun,
    )

    def require(condition: bool) -> None:
        if not condition:
            raise ValueError("Imported data does not match the input manifest.")

    run = await session.get(IssueImportRun, source_key)
    require(run is not None and run.manifest_hash == manifest.digest)
    for doc in manifest.documents:
        document_id = import_id(source_key, "document", doc.path)
        document = await session.get(IssueDocument, document_id)
        version = await session.get(IssueDocumentVersion, (document_id, 1))
        require(document is not None and document.import_source_key == doc.path)
        require(
            version is not None
            and version.content == doc.content
            and version.sha256 == doc.sha256
            and hashlib.sha256(version.content.encode("utf8")).hexdigest() == doc.sha256
        )
    for original in manifest.issues:
        issue_id = import_id(source_key, "issue", original.id)
        issue = await session.get(Issue, issue_id)
        require(issue is not None)
        assert issue is not None
        require(issue.issue_key == original.id and issue.revision == 1)
        for key, expected in original.model_dump(
            exclude={"id", "area", "history", "evidence"}
        ).items():
            require(getattr(issue, key) == expected)
        category = await session.get(IssueCategory, issue.category_id)
        require(
            category is not None
            and category.code == original.area
            and category.name == CATEGORY_NAMES[original.area]
        )
        assert category is not None
        root_category = (
            await session.get(IssueCategory, category.parent_id) if category.parent_id else None
        )
        require(
            root_category is not None
            and root_category.parent_id is None
            and root_category.code == category_parent_code(original.area)
        )
        events = list(
            (await session.scalars(select(IssueEvent).where(IssueEvent.issue_id == issue_id))).all()
        )
        require(len(events) == len(original.history))
        for index, event in enumerate(original.history):
            stored = next(
                (
                    item
                    for item in events
                    if item.id == import_id(source_key, "event", f"{original.id}:{index}")
                ),
                None,
            )
            require(
                stored is not None
                and stored.event_date == event.date
                and stored.description == event.event
                and stored.kind == "imported"
            )
        links = list(
            (
                await session.scalars(
                    select(IssueDocumentLink)
                    .where(IssueDocumentLink.issue_id == issue_id)
                    .order_by(IssueDocumentLink.sort_order)
                )
            ).all()
        )
        require(
            [(str(item.document_id), item.version) for item in links]
            == [(str(import_id(source_key, "document", name)), 1) for name in original.evidence]
        )
    return {**manifest.summary(), "result": "verified"}


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
