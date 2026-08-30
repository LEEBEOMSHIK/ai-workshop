from pathlib import Path
from typing import Protocol

from ai_workshop.labs.rag.parsing.contracts import (
    ConflictingFormatError,
    ParserPort,
    UnsupportedParserError,
)


class _RegisteredParser(ParserPort, Protocol):
    media_types: frozenset[str]
    suffixes: frozenset[str]


class ParserRegistry:
    generic_media_types = frozenset({"", "application/octet-stream", "binary/octet-stream"})

    def __init__(self, parsers: tuple[_RegisteredParser, ...]) -> None:
        self.parsers = parsers

    def resolve(self, media_type: str | None, filename: str) -> ParserPort:
        normalized_media_type = (media_type or "").split(";", maxsplit=1)[0].strip().lower()
        suffix = Path(filename).suffix.lower()
        media_type_parser = next(
            (parser for parser in self.parsers if normalized_media_type in parser.media_types), None
        )
        suffix_parser = next((parser for parser in self.parsers if suffix in parser.suffixes), None)
        if normalized_media_type not in self.generic_media_types:
            if media_type_parser is None:
                raise UnsupportedParserError(media_type or "", filename)
            if suffix_parser is not None and suffix_parser is not media_type_parser:
                raise ConflictingFormatError(media_type or "", filename)
            return media_type_parser
        if suffix_parser is not None:
            return suffix_parser
        raise UnsupportedParserError(media_type or "", filename)
