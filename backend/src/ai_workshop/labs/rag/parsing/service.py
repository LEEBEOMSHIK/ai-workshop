from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory

from ai_workshop.labs.rag.documents.domain import ParsedDocument
from ai_workshop.labs.rag.models.document_processing import DocumentProcessingSpec
from ai_workshop.labs.rag.parsing.contracts import ParseRequest, ParserPort, UnsupportedParserError
from ai_workshop.labs.rag.parsing.registry import ParserRegistry
from ai_workshop.platform.assets.domain import AssetVersion
from ai_workshop.platform.assets.storage import ObjectStore


class ParsingService:
    def __init__(
        self,
        object_store: ObjectStore,
        registry: ParserRegistry,
        *,
        profile_parser_factory: Callable[[str, DocumentProcessingSpec], ParserPort | None]
        | None = None,
    ) -> None:
        self.object_store = object_store
        self.registry = registry
        self.profile_parser_factory = profile_parser_factory

    async def materialize_and_parse(
        self,
        asset_version: AssetVersion,
        filename: str,
        *,
        processing_spec: DocumentProcessingSpec | None = None,
    ) -> ParsedDocument:
        temporary_directory = TemporaryDirectory(prefix="rag-parser-")
        try:
            path = Path(temporary_directory.name) / Path(filename).name
            with path.open("xb") as destination:
                async for chunk in self.object_store.open(asset_version.object_key):
                    destination.write(chunk)
            parser = (
                self.profile_parser_factory(asset_version.media_type, processing_spec)
                if processing_spec is not None and self.profile_parser_factory is not None
                else None
            )
            parser = parser or self.registry.resolve(asset_version.media_type, filename)
            if processing_spec is not None:
                route = processing_spec.parser_routes.get(asset_version.media_type)
                if route is None or route.name != getattr(parser, "parser_name", None):
                    raise UnsupportedParserError(asset_version.media_type, filename)
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
