import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path

from ai_workshop.config import get_settings
from ai_workshop.labs.rag.models.catalog import (
    CatalogConflictError,
    CatalogImportResult,
    ModelCatalogImporter,
    load_model_catalog,
)
from ai_workshop.labs.rag.models.repository import SqlAlchemyModelRegistryRepository
from ai_workshop.platform.identity import cli as identity_cli
from ai_workshop.shared.db import create_engine, create_session_factory


async def register_rag_models(catalog_dir: Path) -> CatalogImportResult:
    definitions = load_model_catalog(catalog_dir)
    engine = create_engine(get_settings())
    sessions = create_session_factory(engine)
    try:
        async with sessions.begin() as session:
            return await ModelCatalogImporter(
                SqlAlchemyModelRegistryRepository(session)
            ).import_definitions(definitions)
    finally:
        await engine.dispose()


def _default_catalog_dir() -> Path:
    application_root = Path(__file__).resolve().parents[2]
    candidates = (
        application_root / "model-profiles" / "rag" / "models",
        application_root.parent / "model-profiles" / "rag" / "models",
    )
    return next((path for path in candidates if path.is_dir()), candidates[0])


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="ai-workshop")
    subparsers = parser.add_subparsers(dest="command", required=True)
    identity_cli.add_bootstrap_owner_parser(subparsers)
    register = subparsers.add_parser("register-rag-models")
    register.add_argument(
        "--catalog-dir",
        type=Path,
        default=_default_catalog_dir(),
    )
    args = parser.parse_args(argv)

    if args.command == "bootstrap-owner":
        asyncio.run(identity_cli.bootstrap_owner(args.name, args.email))
        return
    try:
        result = asyncio.run(register_rag_models(args.catalog_dir))
    except CatalogConflictError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"RAG model definitions: inserted={result.inserted}, unchanged={result.unchanged}")
