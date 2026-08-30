from uuid import uuid4

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.retrieval.domain import (
    FrozenIndexTarget,
    ResolvedSearchScope,
)
from ai_workshop.labs.rag.retrieval.elasticsearch import build_scope_filter


def test_exact_snapshot_target_filters_concrete_builds_and_asset_versions() -> None:
    profile_id = uuid4()
    build_ids = (uuid4(), uuid4())
    asset_version_ids = (uuid4(), uuid4())
    target = FrozenIndexTarget(
        descriptor=IndexDescriptor(768, "cosine"),
        indexing_profile_id=profile_id,
        index_names=("rag-profile-build-a", "rag-profile-build-b"),
        index_build_ids=build_ids,
        asset_version_ids=asset_version_ids,
    )
    scope = ResolvedSearchScope(
        workspace_ids=(uuid4(),),
        folder_ids=(),
        active_only=False,
        ready_only=True,
        asset_version_ids=asset_version_ids[:1],
        index_build_ids=build_ids,
    )

    filters = build_scope_filter(uuid4(), scope)

    assert target.name == "rag-profile-build-a,rag-profile-build-b"
    assert {"terms": {"asset_version_id": [str(asset_version_ids[0])]}} in filters
    assert {"terms": {"index_build_id": [str(item) for item in build_ids]}} in filters
