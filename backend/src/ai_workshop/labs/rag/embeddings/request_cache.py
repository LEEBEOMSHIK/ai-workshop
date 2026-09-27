"""Request-owned embedding reuse; never retain private text between requests."""

from collections.abc import Sequence

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort, EmbeddingValidationError


class RequestScopedEmbedding:
    def __init__(self, delegate: EmbeddingPort) -> None:
        self.delegate = delegate
        self.dimension = delegate.dimension
        self._queries: dict[str, tuple[float, ...]] = {}
        self._documents: dict[str, tuple[float, ...]] = {}

    def count_tokens(self, text: str) -> int:
        return self.delegate.count_tokens(text)

    def count_query_tokens(self, text: str) -> int:
        return self.delegate.count_query_tokens(text)

    def encode_query(self, text: str) -> list[float]:
        if text not in self._queries:
            self._queries[text] = tuple(self.delegate.encode_query(text))
        return list(self._queries[text])

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(text for text in texts if text not in self._documents))
        if missing:
            vectors = self.delegate.encode_documents(missing)
            if len(vectors) != len(missing):
                raise EmbeddingValidationError("Embedding output count must match document inputs.")
            # Build the whole batch before updating: failed batches must not leave
            # partial entries. Tuples also isolate the cache from caller mutation.
            encoded = {text: tuple(vector) for text, vector in zip(missing, vectors, strict=True)}
            self._documents.update(encoded)
        return [list(self._documents[text]) for text in texts]
