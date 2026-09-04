from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.openai_responses import OpenAIResponsesRuntime
from ai_workshop.labs.rag.generation.runtime_resolver import (
    builtin_generation_runtime_factories,
)


def deployment() -> ModelDeploymentVersion:
    return ModelDeploymentVersion(
        id=UUID("91000000-0000-0000-0000-000000000001"),
        deployment_id=UUID("91000000-0000-0000-0000-000000000002"),
        version=1,
        display_name="Synthetic OpenAI contract",
        description="Public fixture",
        model_definition_id=UUID("21000000-0000-0000-0000-000000000001"),
        provider=ProviderKind.OPENAI_RESPONSES,
        location=ExecutionLocation.EXTERNAL,
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        provider_model_id="gpt-synthetic-2026-01-01",
        endpoint_ref="openai-primary",
        secret_ref="openai-key",
        capabilities=frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
        external_transfer=True,
        transmitted_data_categories=("question",),
        data_processing_notice_ref="public-notice-v1",
        timeout_seconds=5.0,
        max_retries=0,
        retry_backoff_seconds=0.0,
        healthcheck_enabled=True,
        development_only=False,
        created_by=UUID("91000000-0000-0000-0000-000000000003"),
        created_at=datetime.now(UTC),
    )


def test_builtin_factory_registers_exact_openai_provider_without_calling_network() -> None:
    factories = builtin_generation_runtime_factories()

    runtime = factories[ProviderKind.OPENAI_RESPONSES](
        deployment(),
        "https://api.example.invalid/v1",
        "synthetic-secret",
    )

    assert isinstance(runtime, OpenAIResponsesRuntime)
    assert set(factories) == {
        ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        ProviderKind.OPENAI_RESPONSES,
    }


def test_arbitrary_or_proxy_clients_and_factories_cannot_be_injected() -> None:
    unsafe_proxy_client = httpx.AsyncClient(trust_env=True, follow_redirects=False)
    unsafe_redirect_client = httpx.AsyncClient(trust_env=False, follow_redirects=True)
    explicit_proxy_client = httpx.AsyncClient(
        proxy="http://proxy-canary.invalid:8080",
        trust_env=False,
        follow_redirects=False,
    )
    try:
        for client in (
            unsafe_proxy_client,
            unsafe_redirect_client,
            explicit_proxy_client,
        ):
            with pytest.raises((TypeError, ValueError)):
                OpenAIResponsesRuntime(
                    deployment=deployment(),
                    endpoint="https://api.example.invalid/v1",
                    api_key="synthetic-secret",
                    client=client,  # type: ignore[call-arg]
                )
        with pytest.raises(TypeError):
            OpenAIResponsesRuntime(
                deployment=deployment(),
                endpoint="https://api.example.invalid/v1",
                api_key="synthetic-secret",
                client_factory=lambda: explicit_proxy_client,  # type: ignore[call-arg]
            )
    finally:
        import asyncio

        asyncio.run(unsafe_proxy_client.aclose())
        asyncio.run(unsafe_redirect_client.aclose())
        asyncio.run(explicit_proxy_client.aclose())


def test_production_constructor_does_not_accept_even_a_mock_transport() -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200))

    with pytest.raises(TypeError):
        OpenAIResponsesRuntime(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,  # type: ignore[call-arg]
        )


def test_private_test_seam_rejects_every_non_exact_mock_transport() -> None:
    class MockTransportSubclass(httpx.MockTransport):
        pass

    transports = (
        httpx.AsyncHTTPTransport(),
        httpx.AsyncHTTPTransport(proxy="http://proxy-canary.invalid:8080"),
        MockTransportSubclass(lambda _: httpx.Response(200)),
    )
    try:
        for transport in transports:
            with pytest.raises(ValueError):
                OpenAIResponsesRuntime._for_test(
                    deployment=deployment(),
                    endpoint="https://api.example.invalid/v1",
                    api_key="synthetic-secret",
                    transport=transport,  # type: ignore[arg-type]
                )
    finally:
        import asyncio

        for transport in transports:
            asyncio.run(transport.aclose())


def test_builtin_factory_has_no_transport_test_seam() -> None:
    factory = builtin_generation_runtime_factories()[ProviderKind.OPENAI_RESPONSES]
    transport = httpx.MockTransport(lambda _: httpx.Response(200))

    with pytest.raises(TypeError):
        factory(
            deployment(),
            "https://api.example.invalid/v1",
            "synthetic-secret",
            transport=transport,  # type: ignore[call-arg]
        )
