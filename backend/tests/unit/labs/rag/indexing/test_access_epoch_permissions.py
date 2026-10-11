"""Actual request policy denies mutations and cross-namespace requests."""

from uuid import UUID

import pytest

from ai_workshop.infrastructure.search.access_credentials import AccessCredentialError
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions


def policy():
    return AccessEpochPermissions("ai-workshop-rag", ((UUID(int=123), None),))


def test_reader_and_collector_cannot_mutate_or_access_other_namespaces():
    p = policy()
    name = "ai-workshop-rag-00000000-0000-0000-0000-00000000007b-active"
    p.authorize("reader", "search", (name,))
    p.authorize("writer", "update_aliases", (name,))
    for role, method, names in [
        ("reader", "update_aliases", (name,)),
        ("collector", "bulk", (name,)),
        ("writer", "search", ("other-documents",)),
        ("writer", "search", (".security",)),
        ("writer", "create_api_key", ()),
        ("writer", "put_user", ()),
        ("writer", "remote_cluster", ()),
        ("writer", "search", ("*",)),
    ]:
        with pytest.raises(AccessCredentialError):
            p.authorize(role, method, names)
    assert p.descriptor("writer")["indices"][0]["allow_restricted_indices"] is False
    assert p.descriptor("reader")["indices"][0]["privileges"] == ["read", "view_index_metadata"]


def test_future_builds_are_scoped_to_existing_profile_namespace():
    p = policy()
    p.authorize(
        "writer",
        "create",
        (
            "ai-workshop-rag-00000000-0000-0000-0000-00000000007b-00000000-0000-0000-0000-000000000099",
        ),
    )
    with pytest.raises(AccessCredentialError):
        p.authorize(
            "writer", "create", ("ai-workshop-rag-00000000-0000-0000-0000-00000000007c-active",)
        )
