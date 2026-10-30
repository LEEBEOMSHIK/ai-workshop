"""Request-owned embedding reuse; never retain private text between requests."""

from collections.abc import Sequence

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort, EmbeddingValidationError
from ai_workshop.labs.rag.executions.operation_timings import measure_operation


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
        reused = text in self._queries
        with measure_operation("embedding.query", items=1, reused_items=int(reused)):
            if not reused:
                self._queries[text] = tuple(self.delegate.encode_query(text))
            return list(self._queries[text])

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        missing = list(dict.fromkeys(text for text in texts if text not in self._documents))
        with measure_operation(
            "embedding.documents", items=len(texts), reused_items=len(texts) - len(missing),
        ):
            if missing:
                vectors = self.delegate.encode_documents(missing)
                if len(vectors) != len(missing):
                    raise EmbeddingValidationError(
                        "Embedding output count must match document inputs."
                    )
                # Build the batch before updating so failures cannot leave partial entries.
                encoded = {
                    text: tuple(vector) for text, vector in zip(missing, vectors, strict=True)
                }
                self._documents.update(encoded)
            return [list(self._documents[text]) for text in texts]
