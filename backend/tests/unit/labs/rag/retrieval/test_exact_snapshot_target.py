from uuid import uuid4

import pytest

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
    descriptor = IndexDescriptor(768, "cosine")
    target = FrozenIndexTarget(
        descriptor=descriptor,
        index_prefix="ai-workshop-rag",
        indexing_profile_id=profile_id,
        index_names=tuple(
            descriptor.concrete_index_name("ai-workshop-rag", profile_id, build_id)
            for build_id in build_ids
        ),
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

    assert target.index_names == tuple(
        descriptor.concrete_index_name("ai-workshop-rag", profile_id, build_id)
        for build_id in build_ids
    )
    assert {"terms": {"asset_version_id": [str(asset_version_ids[0])]}} in filters
    assert {"terms": {"index_build_id": [str(item) for item in build_ids]}} in filters


@pytest.mark.parametrize(
    "corrupted_name",
    [
        "ai-workshop-rag,alias",
        "ai-workshop-rag-*",
        "ai-workshop-rag-active",
        " ai-workshop-rag ",
        "../ai-workshop-rag",
    ],
)
def test_frozen_target_rejects_non_physical_or_injected_index_name(
    corrupted_name: str,
) -> None:
    profile_id = uuid4()
    build_id = uuid4()

    with pytest.raises(ValueError, match="physical index"):
        FrozenIndexTarget(
            descriptor=IndexDescriptor(1024, "cosine"),
            index_prefix="ai-workshop-rag",
            indexing_profile_id=profile_id,
            index_names=(corrupted_name,),
            index_build_ids=(build_id,),
            asset_version_ids=(uuid4(),),
        )


def test_frozen_target_rejects_cross_profile_or_wrong_build_name() -> None:
    descriptor = IndexDescriptor(1024, "cosine")
    profile_id = uuid4()
    build_id = uuid4()

    for corrupted_name in (
        descriptor.concrete_index_name("ai-workshop-rag", uuid4(), build_id),
        descriptor.concrete_index_name("ai-workshop-rag", profile_id, uuid4()),
    ):
        with pytest.raises(ValueError, match="physical index"):
            FrozenIndexTarget(
                descriptor=descriptor,
                index_prefix="ai-workshop-rag",
                indexing_profile_id=profile_id,
                index_names=(corrupted_name,),
                index_build_ids=(build_id,),
                asset_version_ids=(uuid4(),),
            )
