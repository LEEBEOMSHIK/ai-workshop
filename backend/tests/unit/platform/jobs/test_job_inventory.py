from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ai_workshop.platform.jobs.inventory import JobMetadataInventory, _Snapshot


def snapshot(*, revision=1, status="succeeded"):
    workspace, document, version, job_id = (uuid4() for _ in range(4))
    job = SimpleNamespace(
        id=job_id,
        workspace_id=workspace,
        asset_version_id=version,
        revision=revision,
        status=status,
    )
    owner = SimpleNamespace(
        job_id=job_id, workspace_id=workspace, document_id=document, asset_version_id=version
    )
    relation = SimpleNamespace(
        workspace_id=workspace,
        document_id=document,
        asset_version_id=version,
        participant="platform_jobs",
        kind="job",
        resource_id=job_id,
        resource_revision=revision,
        relation_kind="derived_artifact",
    )
    return _Snapshot(
        workspace,
        document,
        (SimpleNamespace(id=document, workspace_id=workspace),),
        (SimpleNamespace(id=version, document_id=document),),
        (job,),
        (owner,),
        (relation,),
    )


def test_terminal_job_does_not_prove_writer_shutdown():
    result = JobMetadataInventory._reconcile(snapshot())
    assert result == {"writer_unconfirmed"}


def test_legacy_job_is_not_adopted_and_missing_owner_is_blocked():
    current = snapshot(revision=None)
    current = replace(current, owners=(), relations=())
    assert JobMetadataInventory._reconcile(current) == {"legacy_untracked", "writer_unconfirmed"}
    tracked = replace(snapshot(), owners=())
    assert "ownership_mismatch" in JobMetadataInventory._reconcile(tracked)


@pytest.mark.parametrize(
    "field,value",
    [("resource_revision", 99), ("kind", "foreign"), ("relation_kind", "source_copy")],
)
def test_wrong_relation_never_certifies_metadata(field, value):
    current = snapshot()
    setattr(current.relations[0], field, value)
    assert "relation_mismatch" in JobMetadataInventory._reconcile(current)


def test_retargeted_job_and_orphan_owner_are_detected():
    current = snapshot()
    current.jobs[0].workspace_id = uuid4()
    assert "ownership_mismatch" in JobMetadataInventory._reconcile(current)
    current = replace(current, jobs=())
    assert "ownership_mismatch" in JobMetadataInventory._reconcile(current)
    assert "relation_mismatch" in JobMetadataInventory._reconcile(current)
