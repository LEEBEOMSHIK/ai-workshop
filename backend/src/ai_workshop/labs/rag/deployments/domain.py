from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class ProviderKind(StrEnum):
    LOCAL_OPENAI_COMPATIBLE = "local_openai_compatible"
    OPENAI_RESPONSES = "openai_responses"


class ExecutionLocation(StrEnum):
    LOCAL = "local"
    ON_PREMISE = "on_premise"
    EXTERNAL = "external"


class DeploymentEnvironment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class DeploymentCapability(StrEnum):
    STRUCTURED_OUTPUT = "structured_output"
    CONTEXTUALIZATION = "contextualization"
    TOKEN_ACCOUNTING = "token_accounting"


class DeploymentValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ModelDeploymentVersion:
    id: UUID
    deployment_id: UUID
    version: int
    display_name: str
    description: str
    model_definition_id: UUID
    provider: ProviderKind
    location: ExecutionLocation
    allowed_environments: tuple[DeploymentEnvironment, ...]
    provider_model_id: str
    endpoint_ref: str
    secret_ref: str | None
    capabilities: frozenset[DeploymentCapability]
    external_transfer: bool
    transmitted_data_categories: tuple[str, ...]
    data_processing_notice_ref: str | None
    timeout_seconds: float
    max_retries: int
    retry_backoff_seconds: float
    healthcheck_enabled: bool
    development_only: bool
    created_by: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.provider, ProviderKind):
            raise DeploymentValidationError("A deployment requires a named Provider kind.")
        if not isinstance(self.location, ExecutionLocation):
            raise DeploymentValidationError("A deployment requires a named execution location.")
        clean_name = self.display_name.strip()
        if not clean_name:
            raise DeploymentValidationError("A deployment display name is required.")
        if isinstance(self.version, bool) or self.version < 1:
            raise DeploymentValidationError("A deployment version must be positive.")
        if isinstance(self.timeout_seconds, bool) or self.timeout_seconds <= 0:
            raise DeploymentValidationError("A deployment timeout must be positive.")
        if isinstance(self.max_retries, bool) or self.max_retries < 0:
            raise DeploymentValidationError("Deployment max retries cannot be negative.")
        if (
            isinstance(self.retry_backoff_seconds, bool)
            or self.retry_backoff_seconds < 0
        ):
            raise DeploymentValidationError("Deployment retry backoff cannot be negative.")

        environments = tuple(self.allowed_environments)
        if not environments or any(
            not isinstance(environment, DeploymentEnvironment)
            for environment in environments
        ):
            raise DeploymentValidationError(
                "A deployment requires named allowed environments."
            )
        if len(set(environments)) != len(environments):
            raise DeploymentValidationError("Allowed environments must be unique.")

        capabilities = frozenset(self.capabilities)
        if not capabilities or any(
            not isinstance(capability, DeploymentCapability)
            for capability in capabilities
        ):
            raise DeploymentValidationError(
                "A deployment requires a nonempty named capability set."
            )

        clean_model_id = _clean_required_reference(
            self.provider_model_id, "Provider model ID"
        )
        clean_endpoint_ref = _clean_required_reference(
            self.endpoint_ref, "deployment endpoint reference"
        )

        clean_secret_ref = _clean_optional_reference(self.secret_ref, "secret")
        clean_notice_ref = _clean_optional_reference(
            self.data_processing_notice_ref, "notice"
        )
        categories = tuple(category.strip() for category in self.transmitted_data_categories)
        if any(not category for category in categories):
            raise DeploymentValidationError(
                "External transfer categories must have nonempty names."
            )
        if len(set(categories)) != len(categories):
            raise DeploymentValidationError("External transfer categories must be unique.")

        is_external = self.location is ExecutionLocation.EXTERNAL
        if is_external != self.external_transfer:
            raise DeploymentValidationError(
                "External location and external transfer must agree."
            )
        if self.provider is ProviderKind.LOCAL_OPENAI_COMPATIBLE and self.location not in {
            ExecutionLocation.LOCAL,
            ExecutionLocation.ON_PREMISE,
        }:
            raise DeploymentValidationError(
                "A local Provider requires local or on-premise execution."
            )
        if self.provider is ProviderKind.OPENAI_RESPONSES:
            if not is_external:
                raise DeploymentValidationError(
                    "OpenAI Responses requires external execution."
                )
            if clean_secret_ref is None:
                raise DeploymentValidationError(
                    "OpenAI Responses requires a secret reference."
                )

        if self.external_transfer:
            if not categories:
                raise DeploymentValidationError(
                    "An external deployment requires transmitted data categories."
                )
            if clean_notice_ref is None:
                raise DeploymentValidationError(
                    "An external deployment requires a data processing notice reference."
                )
        elif categories or clean_notice_ref is not None:
            raise DeploymentValidationError(
                "A non-external deployment cannot declare an external transfer contract."
            )

        object.__setattr__(self, "display_name", clean_name)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "allowed_environments", environments)
        object.__setattr__(self, "provider_model_id", clean_model_id)
        object.__setattr__(self, "endpoint_ref", clean_endpoint_ref)
        object.__setattr__(self, "secret_ref", clean_secret_ref)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "transmitted_data_categories", categories)
        object.__setattr__(self, "data_processing_notice_ref", clean_notice_ref)

    @classmethod
    def create(
        cls,
        *,
        deployment_id: UUID,
        version: int,
        display_name: str,
        description: str,
        model_definition_id: UUID,
        provider: ProviderKind,
        location: ExecutionLocation,
        allowed_environments: Collection[DeploymentEnvironment],
        provider_model_id: str,
        endpoint_ref: str,
        secret_ref: str | None,
        capabilities: Collection[DeploymentCapability],
        external_transfer: bool,
        transmitted_data_categories: Collection[str],
        data_processing_notice_ref: str | None,
        timeout_seconds: float,
        max_retries: int,
        retry_backoff_seconds: float,
        healthcheck_enabled: bool,
        development_only: bool,
        created_by: UUID,
    ) -> "ModelDeploymentVersion":
        return cls(
            id=uuid4(),
            deployment_id=deployment_id,
            version=version,
            display_name=display_name,
            description=description,
            model_definition_id=model_definition_id,
            provider=provider,
            location=location,
            allowed_environments=tuple(allowed_environments),
            provider_model_id=provider_model_id,
            endpoint_ref=endpoint_ref,
            secret_ref=secret_ref,
            capabilities=frozenset(capabilities),
            external_transfer=external_transfer,
            transmitted_data_categories=tuple(transmitted_data_categories),
            data_processing_notice_ref=data_processing_notice_ref,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
            healthcheck_enabled=healthcheck_enabled,
            development_only=development_only,
            created_by=created_by,
            created_at=datetime.now(UTC),
        )


def _clean_optional_reference(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    clean_value = value.strip()
    if not clean_value:
        raise DeploymentValidationError(
            f"A configured {label} reference cannot be empty."
        )
    return clean_value


def _clean_required_reference(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeploymentValidationError(f"A {label} is required.")
    return value.strip()
