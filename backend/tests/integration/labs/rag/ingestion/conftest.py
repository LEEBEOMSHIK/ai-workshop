import pytest_asyncio

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.models.document_processing import (
    LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.shared.db import create_engine, create_session_factory


@pytest_asyncio.fixture(autouse=True)
async def ensure_legacy_document_processing_profile() -> None:
    """Mirror the migration seed for metadata-created integration databases."""
    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            if (
                await session.get(
                    ProfileRecord, LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
                )
                is None
            ):
                session.add(
                    ProfileRecord(
                        id=LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
                        kind="document_processing",
                        name="legacy-text-document-processing",
                        version=1,
                        config={
                            "parser_policy": {
                                "schema_version": 1,
                                "routes": {
                                    "text/plain": {
                                        "name": "plain_text",
                                        "version": "1",
                                    },
                                    "text/markdown": {
                                        "name": "markdown",
                                        "version": "2",
                                    },
                                    "text/x-markdown": {
                                        "name": "markdown",
                                        "version": "2",
                                    },
                                    "application/pdf": {
                                        "name": "pymupdf",
                                        "version": "legacy-per-element",
                                    },
                                },
                            },
                            "ocr": {"enabled": False},
                        },
                        evaluation_state="passed",
                        is_default=True,
                    )
                )
    finally:
        await engine.dispose()
