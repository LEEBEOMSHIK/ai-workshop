import math
import os
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.embeddings.contracts import EmbeddingModelConfig
from ai_workshop.labs.rag.embeddings.sentence_transformers import (
    SentenceTransformerEmbedding,
)
from ai_workshop.labs.rag.models.catalog import load_model_catalog

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AI_WORKSHOP_MODEL_SMOKE") != "1",
        reason="Set AI_WORKSHOP_MODEL_SMOKE=1 to load the pinned local E5 model.",
    ),
]

CATALOG_ROOT = Path(__file__).resolve().parents[6] / "model-profiles" / "rag" / "models"
E5_ID = UUID("00000000-0000-0000-0000-000000000101")


def test_pinned_e5_emits_normalized_768_dimension_document_vector() -> None:
    definition = next(
        model for model in load_model_catalog(CATALOG_ROOT) if model.id == E5_ID
    )
    config = EmbeddingModelConfig.from_definition(
        definition,
        profile_config={"batch_size": 1},
    )
    embedding = SentenceTransformerEmbedding(
        config,
        cache_folder=get_settings().model_cache_root,
        local_files_only=False,
    )

    vector = embedding.encode_documents(["Public synthetic local smoke-test evidence."])[0]

    assert len(vector) == 768
    assert math.isclose(
        math.sqrt(sum(value * value for value in vector)),
        1.0,
        rel_tol=1e-5,
        abs_tol=1e-5,
    )
