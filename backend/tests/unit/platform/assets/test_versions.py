from uuid import uuid4

from ai_workshop.platform.assets.domain import Document, VersionStatus


def test_document_versions_increase_and_do_not_activate_before_processing() -> None:
    document = Document.create(workspace_id=uuid4(), folder_id=None, name="report.pdf")

    first = document.new_version(
        object_key="objects/one",
        sha256="a" * 64,
        media_type="application/pdf",
        size=100,
    )
    second = document.new_version(
        object_key="objects/two",
        sha256="b" * 64,
        media_type="application/pdf",
        size=120,
    )

    assert first.number == 1
    assert second.number == 2
    assert second.status is VersionStatus.STORED
    assert document.active_version_id is None
