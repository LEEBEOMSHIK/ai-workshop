from pathlib import Path
from tempfile import TemporaryDirectory

from ai_workshop.labs.rag.documents.domain import ParsedDocument
from ai_workshop.labs.rag.parsing.contracts import ParseRequest
from ai_workshop.labs.rag.parsing.registry import ParserRegistry
from ai_workshop.platform.assets.domain import AssetVersion
from ai_workshop.platform.assets.storage import ObjectStore


class ParsingService:
    def __init__(self, object_store: ObjectStore, registry: ParserRegistry) -> None:
        self.object_store = object_store
        self.registry = registry

    async def materialize_and_parse(
        self,
        asset_version: AssetVersion,
        filename: str,
    ) -> ParsedDocument:
        temporary_directory = TemporaryDirectory(prefix="rag-parser-")
        try:
            path = Path(temporary_directory.name) / Path(filename).name
            with path.open("xb") as destination:
                async for chunk in self.object_store.open(asset_version.object_key):
                    destination.write(chunk)
            parser = self.registry.resolve(asset_version.media_type, filename)
            return parser.parse(
                ParseRequest(
                    path=path,
                    media_type=asset_version.media_type,
                    filename=filename,
                    asset_version_id=asset_version.id,
                )
            )
        finally:
            temporary_directory.cleanup()
