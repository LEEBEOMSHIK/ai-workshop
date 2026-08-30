from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.models.domain import (
    JsonValue,
    ModelDefinition,
    ModelKind,
    ProfileValidationError,
)


class CatalogConflictError(ValueError):
    pass


class ModelCatalogError(ValueError):
    pass


class _CatalogDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    kind: ModelKind
    name: str = Field(min_length=1, max_length=180)
    version: int = Field(ge=1)
    config: dict[str, JsonValue]


class ModelCatalogRepository(Protocol):
    async def find_model(self, model_id: UUID) -> ModelDefinition | None: ...

    async def find_model_version(
        self, kind: ModelKind, name: str, version: int
    ) -> ModelDefinition | None: ...

    async def add_model(self, model: ModelDefinition) -> ModelDefinition: ...


@dataclass(frozen=True, slots=True)
class CatalogImportResult:
    inserted: int
    unchanged: int


def load_model_catalog(directory: Path) -> tuple[ModelDefinition, ...]:
    if not directory.is_dir():
        raise ModelCatalogError(f"Model catalog directory does not exist: {directory}")
    definitions: list[ModelDefinition] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            document = _CatalogDocument.model_validate(yaml.safe_load(path.read_text("utf-8")))
            definition = replace(
                ModelDefinition.create(
                    kind=document.kind,
                    name=document.name,
                    version=document.version,
                    config=document.config,
                ),
                id=document.id,
            )
        except (
            OSError,
            yaml.YAMLError,
            ValidationError,
            ProfileValidationError,
        ) as exc:
            raise ModelCatalogError(f"Invalid model catalog document: {path.name}") from exc
        if definition.kind is not ModelKind.EMBEDDING:
            raise ModelCatalogError("The built-in RAG model catalog accepts embedding models only.")
        try:
            EmbeddingModelConfig.from_definition(
                definition, profile_config={"batch_size": 1}
            )
        except EmbeddingValidationError as exc:
            raise ModelCatalogError(
                f"Invalid embedding model catalog document: {path.name}"
            ) from exc
        definitions.append(definition)
    if not definitions:
        raise ModelCatalogError("The model catalog contains no YAML definitions.")
    if len({model.id for model in definitions}) != len(definitions):
        raise ModelCatalogError("The model catalog contains a duplicate technical ID.")
    coordinates = {(model.kind, model.name, model.version) for model in definitions}
    if len(coordinates) != len(definitions):
        raise ModelCatalogError("The model catalog contains a duplicate name and version.")
    return tuple(definitions)


class ModelCatalogImporter:
    def __init__(self, repository: ModelCatalogRepository) -> None:
        self.repository = repository

    async def import_definitions(
        self, definitions: Sequence[ModelDefinition]
    ) -> CatalogImportResult:
        inserted = 0
        unchanged = 0
        for definition in definitions:
            by_id = await self.repository.find_model(definition.id)
            by_version = await self.repository.find_model_version(
                definition.kind, definition.name, definition.version
            )
            existing = by_id or by_version
            if existing is None:
                await self.repository.add_model(definition)
                inserted += 1
                continue
            if by_id is not None and by_version is not None and by_id != by_version:
                raise CatalogConflictError(
                    f"Model catalog conflict for {definition.name} version {definition.version}."
                )
            if existing != definition:
                raise CatalogConflictError(
                    f"Model catalog conflict for {definition.name} version {definition.version}."
                )
            unchanged += 1
        return CatalogImportResult(inserted, unchanged)
