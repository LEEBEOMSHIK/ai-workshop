from pathlib import Path
from typing import Protocol

from ai_workshop.labs.rag.parsing.contracts import ParserPort, UnsupportedParserError


class _RegisteredParser(ParserPort, Protocol):
    media_types: frozenset[str]
    suffixes: frozenset[str]


class ParserRegistry:
    def __init__(self, parsers: tuple[_RegisteredParser, ...]) -> None:
        self.parsers = parsers

    def resolve(self, media_type: str, filename: str) -> ParserPort:
        normalized_media_type = media_type.split(";", maxsplit=1)[0].strip().lower()
        suffix = Path(filename).suffix.lower()
        for parser in self.parsers:
            if normalized_media_type in parser.media_types or suffix in parser.suffixes:
                return parser
        raise UnsupportedParserError(media_type, filename)
