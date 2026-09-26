from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.configurations.repository import SqlAlchemyRagConfigurationRepository
from ai_workshop.labs.rag.conversations import attachment_service as module
from ai_workshop.platform.assets.intake_repository import UploadIntakeJournal
from ai_workshop.shared.errors import AppError


@pytest.fixture
def attachment_case(monkeypatch):
    workspace_id, version_id = uuid4(), uuid4()
    user = SimpleNamespace(id=uuid4())
    row = SimpleNamespace(
        id=uuid4(), workspace_id=workspace_id, document_id=uuid4(),
        state="attached", created_at=datetime.now(UTC),
    )
    document = SimpleNamespace(
        id=row.document_id, workspace_id=workspace_id, folder_id=None,
        name="synthetic.txt", metadata_revision=1, active_version_id=version_id,
        versions=[SimpleNamespace(id=version_id, number=1, status="ready")],
    )
    context = SimpleNamespace(
        workspace_options=[SimpleNamespace(id=workspace_id)],
        allowed_workspace_ids=(workspace_id,),
        connection=SimpleNamespace(configuration_version_id=uuid4()),
    )
    config = SimpleNamespace(
        workspace_ids=[workspace_id], indexing_profile_id=uuid4(),
        document_processing_profile_id=uuid4(),
    )
    session = SimpleNamespace(
        scalars=AsyncMock(return_value=[row]), scalar=AsyncMock(),
        add=Mock(), get=AsyncMock(),
    )
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=session)
    manager.__aexit__ = AsyncMock(return_value=False)
    sessions = Mock(return_value=manager)
    sessions.begin.return_value = manager
    service = module.ConversationAttachmentService(sessions, SimpleNamespace())
    service.authorize = AsyncMock(return_value=context)
    service._spaces = AsyncMock(return_value=[SimpleNamespace(id=workspace_id)])
    config_lookup = AsyncMock(return_value=config)
    monkeypatch.setattr(
        SqlAlchemyRagConfigurationRepository, "find_server_bound_version", config_lookup,
    )
    library = SimpleNamespace(document=AsyncMock(return_value=document))
    monkeypatch.setattr(module, "get_library_service", Mock(return_value=library))
    return SimpleNamespace(
        service=service, session=session, context=context, config=config,
        config_lookup=config_lookup, library=library, user=user, row=row,
    )


@pytest.mark.parametrize("excluded_by", ["domain", "configuration", "missing_configuration"])
async def test_private_storage_does_not_imply_generation_readiness(attachment_case, excluded_by):
    case = attachment_case
    if excluded_by == "domain":
        case.context.workspace_options = []
        case.context.allowed_workspace_ids = ()
    elif excluded_by == "configuration":
        case.config.workspace_ids = []
    else:
        case.config_lookup.return_value = None
    result = await case.service.list("demo", uuid4(), case.user)
    assert len(result) == 1
    assert result[0].status == "stored"
    assert result[0].error_code == "attachment_outside_generation_scope"
    assert result[0].document.id == case.row.document_id
    case.library.document.assert_awaited_once()
    case.session.scalar.assert_not_awaited()


async def test_generation_ready_requires_current_scope_and_active_build(attachment_case):
    case = attachment_case
    case.session.scalar.side_effect = [
        SimpleNamespace(id=uuid4(), status="ready"),
        SimpleNamespace(status="ready", is_active=True),
    ]
    result = await case.service.list("demo", uuid4(), case.user)
    assert result[0].status == "ready"
    assert result[0].error_code is None
    assert case.session.scalar.await_count == 2


@pytest.mark.parametrize("denied_by", ["workspace", "document"])
async def test_stored_attachment_never_exposes_revoked_document(attachment_case, denied_by):
    case = attachment_case
    case.context.workspace_options = []
    case.context.allowed_workspace_ids = ()
    if denied_by == "workspace":
        case.service._spaces.return_value = []
    else:
        case.library.document.side_effect = AppError("forbidden", "Denied", 403)
    result = await case.service.list("demo", uuid4(), case.user)
    assert result[0].status == "failed"
    assert result[0].error_code == "attachment_access_changed"
    assert result[0].document is None
    case.session.scalar.assert_not_awaited()
    if denied_by == "workspace":
        case.library.document.assert_not_awaited()


async def test_reservation_rechecks_write_access_before_creating_record(attachment_case):
    case = attachment_case
    case.service._spaces.return_value = []
    with pytest.raises(AppError) as error:
        await case.service.reserve("demo", uuid4(), case.user.id, case.row.workspace_id)
    assert error.value.code == "attachment_workspace_forbidden"
    case.session.add.assert_not_called()
    assert case.service.authorize.call_args.kwargs["lock"] is True


async def test_finalization_rechecks_revoked_write_access(attachment_case, monkeypatch):
    case = attachment_case
    monkeypatch.setattr(UploadIntakeJournal, "prepare_attachment", AsyncMock())
    case.service._spaces.return_value = []
    journal = module.ConversationUploadJournal(
        case.service, slug="demo", conversation_id=uuid4(),
        actor_id=case.user.id, attachment_id=case.row.id,
    )
    original = SimpleNamespace(source=SimpleNamespace(workspace_id=case.row.workspace_id))
    with pytest.raises(AppError) as error:
        await journal.prepare_attachment(case.session, SimpleNamespace(), original)
    assert error.value.code == "attachment_workspace_forbidden"
    case.session.get.assert_not_awaited()
    assert case.service.authorize.call_args.kwargs["lock"] is True
