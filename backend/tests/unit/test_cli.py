from pathlib import Path

from ai_workshop import cli
from ai_workshop.labs.rag.models.catalog import CatalogImportResult


def test_root_cli_preserves_bootstrap_owner_dispatch(monkeypatch) -> None:
    called: list[tuple[str, str]] = []

    async def fake_bootstrap(name: str, email: str) -> None:
        called.append((name, email))

    monkeypatch.setattr(cli.identity_cli, "bootstrap_owner", fake_bootstrap)

    cli.main(
        [
            "bootstrap-owner",
            "--name",
            "Synthetic Owner",
            "--email",
            "owner@example.test",
        ]
    )

    assert called == [("Synthetic Owner", "owner@example.test")]


def test_root_cli_registers_rag_models_from_explicit_catalog(monkeypatch, tmp_path: Path) -> None:
    called: list[Path] = []

    async def fake_register(catalog_dir: Path) -> CatalogImportResult:
        called.append(catalog_dir)
        return CatalogImportResult(inserted=2, unchanged=0)

    monkeypatch.setattr(cli, "register_rag_models", fake_register)

    cli.main(["register-rag-models", "--catalog-dir", str(tmp_path)])

    assert called == [tmp_path]
