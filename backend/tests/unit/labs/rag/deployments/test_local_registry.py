from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.deployments.schemas import DeploymentVersionCreate
from ai_workshop.labs.rag.deployments.service import DeploymentRegistryService, DeploymentRepository
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.generation.test_local_runtime_resolution import local_deployment, spec


def request() -> DeploymentVersionCreate:
    selected = local_deployment()
    return DeploymentVersionCreate.model_validate(
        {name: getattr(selected, name) for name in DeploymentVersionCreate.model_fields}
    )


@pytest.mark.parametrize("wrong_model", [False, True])
async def test_missing_or_mismatched_model_fails_before_repository(
    tmp_path: Path,
    wrong_model: bool,
) -> None:
    service = DeploymentRegistryService(
        cast(DeploymentRepository, object()),
        endpoint_refs={},
        secret_refs={},
        local_model_refs={
            "local-test": spec(tmp_path).model_copy(update={"model_id": "different/model"})
        }
        if wrong_model
        else {},
    )
    with pytest.raises(AppError) as caught:
        await service.create_identity(request(), actor_id=uuid4())
    assert caught.value.code == "deployment_not_ready"


def test_local_registry_accepts_named_model_and_preserves_reference(tmp_path: Path) -> None:
    service = DeploymentRegistryService(
        cast(DeploymentRepository, object()),
        endpoint_refs={},
        secret_refs={},
        local_model_refs={"local-test": spec(tmp_path)},
    )
    selected = request()
    service._validate_references(selected)
    built = service._build_version(selected, deployment_id=uuid4(), version=1, actor_id=uuid4())
    assert built.local_model_ref == "local-test"
    assert built.endpoint_ref is None
