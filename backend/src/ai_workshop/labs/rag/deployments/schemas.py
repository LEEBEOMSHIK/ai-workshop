from datetime import datetime
from typing import TYPE_CHECKING, Literal, Self, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ProviderKind,
)
from ai_workshop.labs.rag.deployments.repository import DeploymentCatalogEntry
from ai_workshop.labs.rag.generation.domain import (
    EXTERNAL_GENERATION_DISCLOSURE_VERSION,
    ExternalGenerationDisclosureVersion,
    NonExternalGenerationDisclosureVersion,
    generation_disclosure,
)

if TYPE_CHECKING:
    from ai_workshop.labs.rag.deployments.service import DeploymentHealthResult


class DeploymentVersionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=1000)
    model_definition_id: UUID
    provider: ProviderKind
    location: ExecutionLocation
    allowed_environments: list[DeploymentEnvironment] = Field(min_length=1)
    provider_model_id: str = Field(min_length=1, max_length=180)
    endpoint_ref: str = Field(min_length=1, max_length=120)
    secret_ref: str | None = Field(default=None, min_length=1, max_length=120)
    capabilities: set[DeploymentCapability] = Field(min_length=1)
    external_transfer: bool
    transmitted_data_categories: list[str] = Field(default_factory=list)
    data_processing_notice_ref: str | None = Field(
        default=None, min_length=1, max_length=180
    )
    timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    retry_backoff_seconds: float = Field(ge=0)
    healthcheck_enabled: bool
    development_only: bool


class DeploymentReadinessResponse(BaseModel):
    ready: bool
    reason_codes: list[str]


class DeploymentHealthResponse(BaseModel):
    status: str
    safe_error_code: str | None
    provider: ProviderKind
    provider_model_id: str
    observed_provider_model_id: str | None
    latency_ms: int
    checked_at: datetime

    @classmethod
    def from_result(cls, result: "DeploymentHealthResult") -> Self:
        return cls(
            status=result.status,
            safe_error_code=result.safe_error_code,
            provider=result.provider,
            provider_model_id=result.provider_model_id,
            observed_provider_model_id=result.observed_provider_model_id,
            latency_ms=result.latency_ms,
            checked_at=result.checked_at,
        )


class DeploymentLatestHealthResponse(BaseModel):
    status: str
    safe_error_code: str | None
    observed_provider_model_id: str | None
    latency_ms: int | None
    checked_at: datetime


class DeploymentApprovalResponse(BaseModel):
    required: Literal[True]
    disclosure_version: ExternalGenerationDisclosureVersion
    disclosure: str
    transmitted_data_categories: list[str]


class DeploymentNoApprovalResponse(BaseModel):
    required: Literal[False]
    disclosure_version: NonExternalGenerationDisclosureVersion
    disclosure: str
    transmitted_data_categories: list[str]


class DeploymentAdminResponse(BaseModel):
    deployment_id: UUID
    version_id: UUID
    version: int
    display_name: str
    description: str
    model_name: str
    model_version: int
    provider: ProviderKind
    provider_model_id: str
    location: ExecutionLocation
    external_transfer: bool
    allowed_environments: list[DeploymentEnvironment]
    capabilities: list[DeploymentCapability]
    secret_configured: bool
    readiness: DeploymentReadinessResponse
    latest_health: DeploymentLatestHealthResponse | None

    @classmethod
    def from_entry(
        cls, entry: DeploymentCatalogEntry, *, secret_configured: bool
    ) -> Self:
        deployment = entry.deployment
        return cls(
            deployment_id=deployment.deployment_id,
            version_id=deployment.id,
            version=deployment.version,
            display_name=deployment.display_name,
            description=deployment.description,
            model_name=entry.model_name,
            model_version=entry.model_version,
            provider=deployment.provider,
            provider_model_id=deployment.provider_model_id,
            location=deployment.location,
            external_transfer=deployment.external_transfer,
            allowed_environments=list(deployment.allowed_environments),
            capabilities=sorted(deployment.capabilities, key=lambda item: item.value),
            secret_configured=secret_configured,
            readiness=_readiness(entry),
            latest_health=_latest_health(entry),
        )


class DeploymentOptionResponse(BaseModel):
    deployment_version_id: UUID
    display_name: str
    model_name: str
    model_version: int
    provider: ProviderKind
    provider_model_id: str
    location: ExecutionLocation
    external_transfer: bool
    allowed_environments: list[DeploymentEnvironment]
    capabilities: list[DeploymentCapability]
    readiness: DeploymentReadinessResponse
    approval: DeploymentApprovalResponse | DeploymentNoApprovalResponse

    @classmethod
    def from_entry(cls, entry: DeploymentCatalogEntry) -> Self:
        deployment = entry.deployment
        disclosure = generation_disclosure(deployment)
        approval: DeploymentApprovalResponse | DeploymentNoApprovalResponse
        if disclosure.required:
            approval = DeploymentApprovalResponse(
                required=True,
                disclosure_version=EXTERNAL_GENERATION_DISCLOSURE_VERSION,
                disclosure=disclosure.text,
                transmitted_data_categories=list(
                    disclosure.transmitted_data_categories
                ),
            )
        else:
            approval = DeploymentNoApprovalResponse(
                required=False,
                disclosure_version=cast(
                    NonExternalGenerationDisclosureVersion,
                    disclosure.version,
                ),
                disclosure=disclosure.text,
                transmitted_data_categories=[],
            )
        return cls(
            deployment_version_id=deployment.id,
            display_name=deployment.display_name,
            model_name=entry.model_name,
            model_version=entry.model_version,
            provider=deployment.provider,
            provider_model_id=deployment.provider_model_id,
            location=deployment.location,
            external_transfer=deployment.external_transfer,
            allowed_environments=list(deployment.allowed_environments),
            capabilities=sorted(deployment.capabilities, key=lambda item: item.value),
            readiness=_readiness(entry),
            approval=approval,
        )


def _latest_health(
    entry: DeploymentCatalogEntry,
) -> DeploymentLatestHealthResponse | None:
    health = entry.latest_health
    if health is None:
        return None
    return DeploymentLatestHealthResponse(
        status=health.status,
        safe_error_code=health.safe_error_code,
        observed_provider_model_id=health.observed_provider_model_id,
        latency_ms=health.latency_ms,
        checked_at=health.created_at,
    )


def _readiness(entry: DeploymentCatalogEntry) -> DeploymentReadinessResponse:
    health = entry.latest_health
    ready = bool(
        health is not None
        and health.status == "ready"
        and health.safe_error_code is None
        and health.observed_provider_model_id == entry.deployment.provider_model_id
    )
    if ready:
        return DeploymentReadinessResponse(ready=True, reason_codes=[])
    reason = (
        health.safe_error_code
        if health is not None and health.safe_error_code is not None
        else "deployment_not_ready"
    )
    return DeploymentReadinessResponse(ready=False, reason_codes=[reason])
