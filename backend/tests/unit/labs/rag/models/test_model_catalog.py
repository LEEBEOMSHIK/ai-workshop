from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.models.catalog import (
    CatalogConflictError,
    ModelCatalogError,
    ModelCatalogImporter,
    load_model_catalog,
)
from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind, freeze_json

CATALOG_ROOT = Path(__file__).resolve().parents[6] / "model-profiles" / "rag" / "models"
E5_ID = UUID("00000000-0000-0000-0000-000000000101")
BGE_ID = UUID("00000000-0000-0000-0000-000000000102")


class MemoryCatalogRepository:
    def __init__(self, models: tuple[ModelDefinition, ...] = ()) -> None:
        self.models = list(models)

    async def find_model(self, model_id: UUID) -> ModelDefinition | None:
        return next((model for model in self.models if model.id == model_id), None)

    async def find_model_version(
        self, kind: ModelKind, name: str, version: int
    ) -> ModelDefinition | None:
        return next(
            (
                model
                for model in self.models
                if model.kind is kind and model.name == name and model.version == version
            ),
            None,
        )

    async def add_model(self, model: ModelDefinition) -> ModelDefinition:
        self.models.append(model)
        return model


def test_builtin_catalog_has_exact_fixed_ids_revisions_and_dense_local_contracts() -> None:
    definitions = load_model_catalog(CATALOG_ROOT)

    assert [(model.id, model.name, model.version) for model in definitions] == [
        (BGE_ID, "bge-m3", 1),
        (E5_ID, "multilingual-e5-base", 1),
    ]
    by_id = {model.id: model for model in definitions}
    assert by_id[E5_ID].config == {
        "repo_id": "intfloat/multilingual-e5-base",
        "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
        "dimension": 768,
        "max_tokens": 512,
        "query_prefix": "query: ",
        "document_prefix": "passage: ",
        "normalize": True,
        "device": "cpu",
        "dtype": "float32",
        "output_mode": "dense",
        "data_policy": "local_only",
    }
    assert by_id[BGE_ID].config["revision"] == (
        "5617a9f61b028005a4858fdac845db406aefb181"
    )
    assert by_id[BGE_ID].config["dimension"] == 1024
    assert by_id[BGE_ID].config["max_tokens"] == 8192
    assert by_id[BGE_ID].config["output_mode"] == "dense"
    assert by_id[BGE_ID].config["data_policy"] == "local_only"


@pytest.mark.asyncio
async def test_identical_catalog_import_is_an_idempotent_noop() -> None:
    definitions = load_model_catalog(CATALOG_ROOT)
    repository = MemoryCatalogRepository()
    importer = ModelCatalogImporter(repository)

    first = await importer.import_definitions(definitions)
    second = await importer.import_definitions(definitions)

    assert (first.inserted, first.unchanged) == (2, 0)
    assert (second.inserted, second.unchanged) == (0, 2)
    assert len(repository.models) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("conflict_kind", ["config", "id", "coordinates"])
async def test_catalog_import_rejects_every_nonidentical_identity_conflict(
    conflict_kind: str,
) -> None:
    definition = load_model_catalog(CATALOG_ROOT)[0]
    if conflict_kind == "config":
        conflict = replace(
            definition,
            config=freeze_json({**dict(definition.config), "dimension": 999}),
        )
    elif conflict_kind == "id":
        conflict = replace(definition, name="another-model")
    else:
        conflict = replace(definition, id=UUID("00000000-0000-0000-0000-000000000199"))
    repository = MemoryCatalogRepository((conflict,))

    with pytest.raises(CatalogConflictError, match="conflict"):
        await ModelCatalogImporter(repository).import_definitions((definition,))

    assert repository.models == [conflict]


def test_catalog_rejects_literal_secret_configuration(tmp_path: Path) -> None:
    (tmp_path / "unsafe.yaml").write_text(
        """
id: 00000000-0000-0000-0000-000000000199
kind: embedding
name: unsafe-model
version: 1
config:
  repo_id: public/unsafe-model
  revision: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  dimension: 3
  max_tokens: 8
  query_prefix: ""
  document_prefix: ""
  normalize: true
  device: cpu
  dtype: float32
  output_mode: dense
  data_policy: local_only
  api_key: do-not-store-literals
""",
        encoding="utf-8",
    )

    with pytest.raises(ModelCatalogError, match="Invalid model catalog"):
        load_model_catalog(tmp_path)
