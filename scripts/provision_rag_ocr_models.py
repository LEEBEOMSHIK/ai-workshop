import argparse
from pathlib import Path

from ai_workshop.labs.rag.ocr.artifacts import provision_artifacts


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify and install pinned RAG OCR artifacts into the local cache."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    arguments = parser.parse_args()

    installed = provision_artifacts(
        manifest_path=arguments.manifest,
        source_root=arguments.source_root,
        cache_root=arguments.cache_root,
    )
    for path in installed:
        print(path)


if __name__ == "__main__":
    main()
