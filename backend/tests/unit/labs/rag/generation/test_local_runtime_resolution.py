from dataclasses import replace
from pathlib import Path

import pytest
from fastapi import Request
from pydantic import ValidationError

from ai_workshop.config import Settings
from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.local_model_host import LocalModelHost, LocalModelSpec
from ai_workshop.labs.rag.generation.local_runtime_dependency import get_local_model_host
from ai_workshop.labs.rag.generation.local_transformers import LocalTransformersRuntime
from ai_workshop.labs.rag.generation.runtime_resolver import GenerationRuntimeResolver
from ai_workshop.main import create_app
from tests.unit.labs.rag.generation.test_runtime_resolver import allowed_policy, deployment


def spec(tmp_path: Path) -> LocalModelSpec:
    return LocalModelSpec(
        model_id="runtime/exact-model",
        revision="a" * 40,
        snapshot_path=tmp_path,
        max_input_tokens=1024,
    )


def local_deployment():
    return replace(
        deployment(),
        provider=ProviderKind.LOCAL_TRANSFORMERS,
        endpoint_ref=None,
        secret_ref=None,
        max_retries=0,
        local_model_ref="local-test",
    )


def test_resolver_recreation_reuses_host_without_loading(tmp_path: Path) -> None:
    host = LocalModelHost()
    adapters = [
        GenerationRuntimeResolver(
            environment="local",
            endpoint_refs={},
            secret_refs={},
            factories={},
            local_model_refs={"local-test": spec(tmp_path)},
            local_model_host=host,
        )
        .resolve(local_deployment(), allowed_policy())
        .adapter
        for _ in range(2)
    ]
    assert all(isinstance(adapter, LocalTransformersRuntime) for adapter in adapters)
    assert adapters[0] is not adapters[1]
    assert all(adapter.host is host for adapter in adapters)


@pytest.mark.parametrize("missing", ["host", "reference", "model"])
def test_local_resolution_fails_closed(tmp_path: Path, missing: str) -> None:
    selected = spec(tmp_path)
    if missing == "model":
        selected = selected.model_copy(update={"model_id": "different/model"})
    resolver = GenerationRuntimeResolver(
        environment="local",
        endpoint_refs={},
        secret_refs={},
        factories={},
        local_model_refs={} if missing == "reference" else {"local-test": selected},
        local_model_host=None if missing == "host" else LocalModelHost(),
    )
    with pytest.raises(GenerationProviderError, match="deployment_not_ready"):
        resolver.resolve(local_deployment(), allowed_policy())


def test_settings_parse_local_specs_without_loading(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        secret_key="synthetic-test-key" * 3,
        local_model_refs={"local-test": spec(tmp_path)},
    )
    assert settings.local_model_refs["local-test"].revision == "a" * 40


def test_settings_reject_unsafe_local_reference(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            secret_key="synthetic-test-key" * 3,
            local_model_refs={"../private": spec(tmp_path)},
        )


async def test_app_owns_shared_host_and_closes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    closed = []

    async def close(self: LocalModelHost) -> None:
        closed.append(self)

    monkeypatch.setattr(LocalModelHost, "aclose", close)
    app = create_app()
    request = Request({"type": "http", "app": app})
    first = get_local_model_host(request)
    assert get_local_model_host(request) is first
    async with app.router.lifespan_context(app):
        pass
    assert closed == [first]
