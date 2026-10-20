from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal

from pydantic import SecretStr

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentEnvironment,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.secrets import (
    EndpointReferenceResolver,
    SecretReferenceError,
    SecretReferenceResolver,
)
from ai_workshop.labs.rag.generation.contracts import GenerationRuntimePort
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ResolvedGenerationRuntime,
)
from ai_workshop.labs.rag.generation.local_model_host import LocalModelHost, LocalModelSpec
from ai_workshop.labs.rag.generation.local_transformers import LocalTransformersRuntime
from ai_workshop.labs.rag.generation.openai_compatible import (
    LocalOpenAICompatibleRuntime,
)
from ai_workshop.labs.rag.generation.openai_responses import OpenAIResponsesRuntime
from ai_workshop.labs.rag.policies.domain import PolicyDecision

GenerationRuntimeFactory = Callable[
    [ModelDeploymentVersion, str, str | None],
    GenerationRuntimePort,
]


def builtin_generation_runtime_factories(
    *,
    provider_endpoint_dialects: Mapping[str, Literal["openai", "ollama"]] | None = None,
) -> dict[
    ProviderKind,
    GenerationRuntimeFactory,
]:
    dialects = dict(provider_endpoint_dialects or {})
    return {
        ProviderKind.LOCAL_OPENAI_COMPATIBLE: (
            lambda deployment, endpoint, secret: LocalOpenAICompatibleRuntime(
                deployment=deployment,
                endpoint=endpoint,
                api_key=secret,
                dialect=dialects.get(deployment.endpoint_ref or "", "openai"),
            )
        ),
        ProviderKind.OPENAI_RESPONSES: (
            lambda deployment, endpoint, secret: OpenAIResponsesRuntime(
                deployment=deployment,
                endpoint=endpoint,
                api_key=secret or "",
            )
        ),
    }


class GenerationRuntimeResolver:
    def __init__(
        self,
        *,
        environment: str,
        endpoint_refs: Mapping[str, str],
        secret_refs: Mapping[str, SecretStr],
        factories: Mapping[ProviderKind, GenerationRuntimeFactory],
        local_model_refs: Mapping[str, LocalModelSpec] | None = None,
        local_model_host: LocalModelHost | None = None,
    ) -> None:
        self._environment = _normalize_environment(environment)
        self._endpoint_resolver = EndpointReferenceResolver(endpoint_refs)
        self._secret_resolver = SecretReferenceResolver(secret_refs)
        self._factories = dict(factories)
        self._local_model_refs = dict(local_model_refs or {})
        self._local_model_host = local_model_host

    def resolve(
        self,
        deployment: ModelDeploymentVersion,
        policy: PolicyDecision,
    ) -> ResolvedGenerationRuntime:
        if (
            self._environment not in deployment.allowed_environments
            or deployment.development_only
            and self._environment is not DeploymentEnvironment.DEVELOPMENT
        ):
            raise GenerationProviderError(
                "deployment_not_allowed_in_environment",
                retryable=False,
            )
        if not policy.allowed:
            raise GenerationProviderError(
                (
                    policy.reason_code.value
                    if policy.reason_code is not None
                    else "provider_not_allowed"
                ),
                retryable=False,
            )
        if deployment.provider is ProviderKind.LOCAL_TRANSFORMERS:
            spec = self._local_model_refs.get(deployment.local_model_ref or "")
            if (
                spec is None
                or self._local_model_host is None
                or spec.model_id != deployment.provider_model_id
            ):
                raise GenerationProviderError("deployment_not_ready", retryable=False)
            return ResolvedGenerationRuntime(
                deployment,
                LocalTransformersRuntime(
                    deployment=deployment, spec=spec, host=self._local_model_host
                ),
            )
        if (
            deployment.provider is ProviderKind.DEVELOPMENT_CODEX_EXEC
            or deployment.endpoint_ref is None
        ):
            raise GenerationProviderError("deployment_not_ready", retryable=False)
        factory = self._factories.get(deployment.provider)
        if factory is None:
            raise GenerationProviderError("deployment_not_ready", retryable=False)
        try:
            endpoint = self._endpoint_resolver.resolve(deployment.endpoint_ref)
            secret = (
                self._secret_resolver.resolve(deployment.secret_ref).get_secret_value()
                if deployment.secret_ref is not None
                else None
            )
            adapter = factory(deployment, endpoint, secret)
        except (SecretReferenceError, ValueError):
            adapter = None
        if adapter is None:
            raise GenerationProviderError(
                "deployment_not_ready",
                retryable=False,
            ) from None
        return ResolvedGenerationRuntime(deployment, adapter)


def _normalize_environment(environment: str) -> DeploymentEnvironment:
    if environment in {"local", "test"}:
        return DeploymentEnvironment.DEVELOPMENT
    if environment == "production":
        return DeploymentEnvironment.PRODUCTION
    raise GenerationProviderError(
        "deployment_not_allowed_in_environment",
        retryable=False,
    )
