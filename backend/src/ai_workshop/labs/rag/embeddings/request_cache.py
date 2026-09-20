"""Request-owned query reuse; never retain private text between requests."""

from collections.abc import Sequence

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort


class RequestScopedEmbedding:
    def __init__(self, delegate: EmbeddingPort) -> None:
        self.delegate = delegate
        self.dimension = delegate.dimension
        self._queries: dict[str, tuple[float, ...]] = {}

    def count_tokens(self, text: str) -> int:
        return self.delegate.count_tokens(text)

    def count_query_tokens(self, text: str) -> int:
        return self.delegate.count_query_tokens(text)

    def encode_query(self, text: str) -> list[float]:
        if text not in self._queries:
            self._queries[text] = tuple(self.delegate.encode_query(text))
        return list(self._queries[text])

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.delegate.encode_documents(texts)
