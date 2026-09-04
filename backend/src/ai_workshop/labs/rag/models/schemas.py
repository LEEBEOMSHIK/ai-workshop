from typing import Self
from uuid import UUID

import yaml
from pydantic import BaseModel, Field, ValidationError

from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    JsonValue,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
    thaw_json,
)
from ai_workshop.shared.errors import AppError


class ModelCreate(BaseModel):
    kind: ModelKind
    name: str = Field(min_length=1, max_length=180)
    version: int = Field(ge=1)
    config: dict[str, JsonValue]


class ModelResponse(BaseModel):
    id: UUID
    kind: ModelKind
    name: str
    version: int
    config: dict[str, JsonValue]

    @classmethod
    def from_domain(cls, model: ModelDefinition) -> Self:
        config = thaw_json(model.config)
        if not isinstance(config, dict):
            raise TypeError("Model configuration must be a mapping.")
        return cls(
            id=model.id,
            kind=model.kind,
            name=model.name,
            version=model.version,
            config=config,
        )


class ProfileBindingCreate(BaseModel):
    role: ModelKind
    model_id: UUID

    def to_domain(self) -> ProfileModelBinding:
        return ProfileModelBinding(role=self.role, model_id=self.model_id)


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    version: int = Field(ge=1)
    config: dict[str, JsonValue]
    bindings: list[ProfileBindingCreate] = Field(default_factory=list)
    deployment_version_id: UUID | None = None
    evaluation_state: EvaluationState = EvaluationState.DRAFT


class ProfileYamlDocument(ProfileCreate):
    kind: ProfileKind


class ProfileYamlRequest(BaseModel):
    content: str = Field(min_length=1)


def parse_profile_yaml(content: str, *, expected_kind: ProfileKind) -> ProfileYamlDocument:
    try:
        data = yaml.safe_load(content)
        document = ProfileYamlDocument.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        raise AppError("invalid_profile_yaml", "The profile YAML is invalid.", 422) from exc
    if document.kind is not expected_kind:
        raise AppError(
            "invalid_profile_yaml",
            "The YAML profile kind must match the registration endpoint.",
            422,
        )
    return document


class ProfileReadinessResponse(BaseModel):
    ready: bool
    reason_codes: list[str]


class ProfileResponse(BaseModel):
    id: UUID
    kind: ProfileKind
    name: str
    version: int
    config: dict[str, JsonValue]
    bindings: list[ProfileBindingCreate]
    evaluation_state: EvaluationState
    is_default: bool
    deployment_version_id: UUID | None
    legacy: bool
    readiness: ProfileReadinessResponse

    @classmethod
    def from_domain(cls, profile: Profile) -> Self:
        config = thaw_json(profile.config)
        if not isinstance(config, dict):
            raise TypeError("Profile configuration must be a mapping.")
        return cls(
            id=profile.id,
            kind=profile.kind,
            name=profile.name,
            version=profile.version,
            config=config,
            bindings=[
                ProfileBindingCreate(role=item.role, model_id=item.model_id)
                for item in profile.bindings
            ],
            evaluation_state=profile.evaluation_state,
            is_default=profile.is_default,
            deployment_version_id=profile.deployment_version_id,
            legacy=profile.legacy,
            readiness=ProfileReadinessResponse(
                ready=False,
                reason_codes=(
                    ["deployment_not_ready"]
                    if profile.kind is ProfileKind.GENERATION
                    else []
                ),
            ),
        )
