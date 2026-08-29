from uuid import uuid4

from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelKind,
    ProfileKind,
)
from ai_workshop.labs.rag.models.models import ModelDefinitionRecord, ProfileRecord
from ai_workshop.labs.rag.models.repository import _model_to_domain, _profile_to_domain


def test_database_strings_and_json_are_normalized_to_model_domain() -> None:
    record = ModelDefinitionRecord(
        id=uuid4(),
        kind="embedding",
        name="embedding-baseline",
        version=1,
        config={"dimension": 768},
    )

    model = _model_to_domain(record)

    assert model.kind is ModelKind.EMBEDDING
    assert model.config["dimension"] == 768


def test_database_strings_and_bindings_are_normalized_to_profile_domain() -> None:
    profile_id = uuid4()
    record = ProfileRecord(
        id=profile_id,
        kind="retrieval",
        name="bm25-baseline",
        version=1,
        config={"bm25": {}},
        evaluation_state="passed",
        is_default=True,
    )
    record.bindings = []

    profile = _profile_to_domain(record)

    assert profile.kind is ProfileKind.RETRIEVAL
    assert profile.evaluation_state is EvaluationState.PASSED
    assert profile.is_default is True
