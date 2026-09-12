from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ai_workshop.platform.publishing.package import StudySnapshot
from ai_workshop.platform.publishing.public_store import SqlitePublicStudyReader
from ai_workshop.platform.publishing.schemas import PublicStudyCatalog, PublicStudyList
from ai_workshop.platform.publishing.settings import PublicSettings

router = APIRouter(prefix="/api/public", tags=["public-studies"])


def get_public_settings() -> PublicSettings:
    return PublicSettings()  # type: ignore[call-arg]


def get_public_reader(
    settings: Annotated[PublicSettings, Depends(get_public_settings)],
) -> SqlitePublicStudyReader:
    return SqlitePublicStudyReader(settings.store_path)


@router.get("/studies", response_model=PublicStudyList)
async def list_public_studies(
    reader: Annotated[SqlitePublicStudyReader, Depends(get_public_reader)],
    topic_key: str | None = None,
) -> PublicStudyList:
    return PublicStudyList(items=reader.list_published(topic_key))


@router.get("/studies/{slug}", response_model=StudySnapshot)
async def public_study_detail(
    slug: str,
    reader: Annotated[SqlitePublicStudyReader, Depends(get_public_reader)],
) -> StudySnapshot:
    return reader.get(slug)


@router.get("/study-catalog", response_model=PublicStudyCatalog)
def public_study_catalog(
    reader: Annotated[SqlitePublicStudyReader, Depends(get_public_reader)],
    page: Annotated[int, Query(ge=1, le=1_000_000)] = 1,
    topic_key: Annotated[
        str | None, Query(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=128)
    ] = None,
) -> PublicStudyCatalog:
    return reader.catalog(page=page, topic_key=topic_key)


@router.get("/health")
async def public_health() -> dict[str, str]:
    return {"status": "ok"}
