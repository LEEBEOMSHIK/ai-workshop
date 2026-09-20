from collections.abc import Callable
from uuid import uuid4

from ai_workshop.labs.rag.documents.domain import ParsedDocument
from ai_workshop.labs.rag.models.document_processing import DocumentProcessingSpec
from ai_workshop.labs.rag.parsing.contracts import ParseRequest, ParserPort, UnsupportedParserError
from ai_workshop.labs.rag.parsing.registry import ParserRegistry
from ai_workshop.platform.assets.domain import AssetVersion
from ai_workshop.platform.assets.storage import ObjectStore
from ai_workshop.platform.assets.temporary_contracts import (
    TemporaryContext,
    TemporaryOwnershipError,
)
from ai_workshop.platform.assets.temporary_service import TemporaryWorkspaceService


class ParsingService:
    def __init__(
        self,
        object_store: ObjectStore,
        registry: ParserRegistry,
        *,
        temporary_service: TemporaryWorkspaceService,
        profile_parser_factory: Callable[[str, DocumentProcessingSpec], ParserPort | None]
        | None = None,
    ) -> None:
        self.temporary_service = temporary_service
        self.object_store = object_store
        self.registry = registry
        self.profile_parser_factory = profile_parser_factory

    async def materialize_and_parse(
        self,
        asset_version: AssetVersion,
        filename: str,
        *,
        context: TemporaryContext,
        processing_spec: DocumentProcessingSpec | None = None,
    ) -> ParsedDocument:
        if (
            context.source.asset_version_id != asset_version.id
            or context.source.document_id != asset_version.document_id
        ):
            raise TemporaryOwnershipError("source_mismatch")
        lease = await self.temporary_service.open(context, "parsing", coverage="runtime_unverified")
        opaque_runtime_started = False

        def mark_opaque_runtime_started() -> None:
            nonlocal opaque_runtime_started
            opaque_runtime_started = True

        try:
            path = lease.workspace.create_file(f"{uuid4()}.source")
            with path.open("wb") as destination:
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
                    temporary_workspace=lease.workspace,
                    opaque_runtime_started=mark_opaque_runtime_started,
                )
            )
        finally:
            await lease.finish(writer_confirmed=not opaque_runtime_started)
