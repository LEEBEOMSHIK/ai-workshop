from dataclasses import replace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.platform.assets import schemas
from ai_workshop.platform.assets.domain import Document, Folder
from ai_workshop.shared.errors import AppError


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"expected_revision": 1},
        {"destination_folder_id": None},
        {"destination_folder_id": None, "expected_revision": True},
        {"destination_folder_id": None, "expected_revision": "1"},
        {"destination_folder_id": None, "expected_revision": 0},
        {"destination_folder_id": None, "expected_revision": 1, "name": "extra"},
    ],
)
def test_move_payload_is_required_and_strict(payload):
    assert hasattr(schemas, "AssetMoveRequest")
    with pytest.raises(ValidationError):
        schemas.AssetMoveRequest.model_validate(payload)


def test_null_destination_round_trips_and_new_assets_start_at_one():
    assert hasattr(schemas, "AssetMoveRequest")
    request = schemas.AssetMoveRequest(destination_folder_id=None, expected_revision=1)
    assert request.model_dump() == {"destination_folder_id": None, "expected_revision": 1}
    workspace = uuid4()
    assert Document.create(workspace_id=workspace, folder_id=None, name="a").metadata_revision == 1
    assert Folder.create(workspace_id=workspace, parent_id=None, name="a").metadata_revision == 1


def test_hierarchy_rejects_cycles_broken_ancestry_and_subtree_overflow():
    from ai_workshop.platform.assets.movement import FolderHierarchy

    workspace = uuid4()
    a = Folder.create(workspace_id=workspace, parent_id=None, name="a")
    b = Folder.create(workspace_id=workspace, parent_id=a.id, name="b")
    c = Folder.create(workspace_id=workspace, parent_id=None, name="c")
    hierarchy = FolderHierarchy([a, b, c], max_depth=2)
    for destination in (a.id, b.id):
        with pytest.raises(AppError) as error:
            hierarchy.validate_move(a.id, destination)
        assert error.value.code == "folder_cycle"
    with pytest.raises(AppError) as error:
        hierarchy.validate_move(a.id, c.id)
    assert error.value.code == "folder_depth_exceeded"
    hierarchy.validate_move(b.id, c.id)
    with pytest.raises(AppError) as error:
        FolderHierarchy([replace(a, parent_id=uuid4()), b], max_depth=64).validate_move(a.id, None)
    assert error.value.code == "folder_hierarchy_invalid"


def test_stored_revision_is_exposed_in_folder_and_document_responses():
    workspace = uuid4()
    folder = Folder.create(workspace_id=workspace, parent_id=None, name="a")
    folder.metadata_revision = 8
    document = Document.create(workspace_id=workspace, folder_id=None, name="a")
    document.metadata_revision = 11
    document.new_version(object_key="synthetic", sha256="0" * 64, media_type="text/plain", size=1)
    assert schemas.FolderResponse.from_domain(folder).metadata_revision == 8
    assert schemas.DocumentResponse.from_domain(document).metadata_revision == 11


def test_existing_cycle_and_broken_destination_fail_closed():
    from ai_workshop.platform.assets.movement import FolderHierarchy

    workspace = uuid4()
    a = Folder.create(workspace_id=workspace, parent_id=None, name="a")
    b = Folder.create(workspace_id=workspace, parent_id=a.id, name="b")
    for folders, source, destination in (
        ([replace(a, parent_id=b.id), b], a.id, None),
        ([a, replace(b, parent_id=uuid4())], a.id, b.id),
    ):
        with pytest.raises(AppError) as error:
            FolderHierarchy(folders, max_depth=64).validate_move(source, destination)
        assert error.value.code == "folder_hierarchy_invalid"


@pytest.mark.asyncio
async def test_document_noop_rejects_broken_existing_folder_graph():
    from ai_workshop.platform.assets.movement import AssetMovementService
    from tests.unit.platform.assets.test_asset_service import MemoryAssetRepository, owner

    class Repository(MemoryAssetRepository):
        async def folder_belongs_to(self, folder_id, workspace_id):
            return True

        async def list_folders(self, user_id, workspace_id):
            return [Folder(folder_id, workspace_id, uuid4(), "broken")]

    workspace, folder_id = uuid4(), uuid4()
    repository = Repository()
    repository.saved = Document.create(workspace_id=workspace, folder_id=folder_id, name="a")
    with pytest.raises(AppError) as error:
        await AssetMovementService(repository, max_depth=64).move_document(
            user=owner(),
            workspace_id=workspace,
            document_id=repository.saved.id,
            destination_folder_id=folder_id,
            expected_revision=1,
        )
    assert error.value.code == "folder_hierarchy_invalid"


@pytest.mark.asyncio
async def test_noop_checks_revision_and_permission_before_returning():
    from ai_workshop.platform.assets.movement import AssetMovementService
    from tests.unit.platform.assets.test_asset_service import MemoryAssetRepository, owner

    repository = MemoryAssetRepository()
    workspace = uuid4()
    repository.saved = Document.create(workspace_id=workspace, folder_id=None, name="a")
    service = AssetMovementService(repository, max_depth=64)
    args = dict(
        user=owner(),
        workspace_id=workspace,
        document_id=repository.saved.id,
        destination_folder_id=None,
    )
    document, changed = await service.move_document(**args, expected_revision=1)
    assert not changed and document.metadata_revision == 1
    with pytest.raises(AppError) as error:
        await service.move_document(**args, expected_revision=2)
    assert error.value.code == "asset_revision_conflict"
    repository.allowed = False
    with pytest.raises(AppError) as error:
        await service.move_document(**args, expected_revision=2)
    assert error.value.status_code == 404


@pytest.mark.parametrize("kind", ["document", "folder"])
def test_move_http_contract_requires_explicit_revision_and_returns_current_metadata(kind):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ai_workshop.platform.assets.api import router
    from ai_workshop.platform.assets.movement import (
        AssetMovementService,
        get_asset_movement_service,
    )
    from ai_workshop.platform.identity.api import get_current_user
    from ai_workshop.shared.errors import register_error_handlers
    from tests.unit.platform.assets.test_asset_service import MemoryAssetRepository, owner

    workspace = uuid4()
    folder = Folder.create(workspace_id=workspace, parent_id=None, name="folder")
    folder.metadata_revision = 7

    class Repository(MemoryAssetRepository):
        async def list_folders(self, user_id, workspace_id):
            return [folder]

    repository = Repository()
    repository.saved = Document.create(workspace_id=workspace, folder_id=None, name="doc")
    repository.saved.metadata_revision = 7
    target = repository.saved.id if kind == "document" else folder.id
    app = FastAPI()
    app.include_router(router)
    register_error_handlers(app)
    app.dependency_overrides[get_current_user] = owner
    app.dependency_overrides[get_asset_movement_service] = lambda: AssetMovementService(
        repository, max_depth=64
    )
    with TestClient(app) as client:
        path = f"/api/v1/workspaces/{workspace}/{kind}s/{target}/move"
        assert client.post(path, json={"expected_revision": 7}).status_code == 422
        response = client.post(path, json={"destination_folder_id": None, "expected_revision": 7})
        assert response.status_code == 200
        assert response.json() == {
            "id": str(target),
            "workspace_id": str(workspace),
            "name": "doc" if kind == "document" else "folder",
            "folder_id" if kind == "document" else "parent_id": None,
            "metadata_revision": 7,
            "changed": False,
        }
        assert (
            client.post(
                path, json={"destination_folder_id": None, "expected_revision": 1}
            ).status_code
            == 409
        )
