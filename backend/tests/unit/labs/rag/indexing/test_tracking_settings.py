import pytest
from pydantic import ValidationError

from ai_workshop.config import Settings


def test_search_binding_is_optional_but_preserves_opaque_cluster_identity() -> None:
    unset = Settings(_env_file=None, secret_key="x" * 32)
    assert unset.rag_index_store_id is None
    assert unset.rag_index_cluster_uuid is None
    configured = Settings(
        _env_file=None,
        secret_key="x" * 32,
        rag_index_store_id="rag_indices",
        rag_index_cluster_uuid="opaque-CLUSTER_1",
    )
    assert configured.rag_index_cluster_uuid == "opaque-CLUSTER_1"


@pytest.mark.parametrize(
    "store,cluster",
    [
        ("rag_indices", None),
        (None, "cluster"),
        ("../store", "cluster"),
        ("rag_indices", ""),
        ("rag_indices", " cluster"),
        ("rag_indices", "cluster\n"),
        ("rag_indices", "https://example.invalid"),
    ],
)
def test_search_binding_rejects_partial_or_unsafe_configuration(
    store: str | None,
    cluster: str | None,
) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            secret_key="x" * 32,
            rag_index_store_id=store,
            rag_index_cluster_uuid=cluster,
        )
