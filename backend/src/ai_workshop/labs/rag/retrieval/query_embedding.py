from collections.abc import Sequence

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingPort,
    EmbeddingRuntimeUnavailableError,
)
from ai_workshop.labs.rag.retrieval.domain import QueryEmbeddingUnavailableError


class RetrievalQueryEmbedding:
    def __init__(self, embedding: EmbeddingPort) -> None:
        self.embedding = embedding
        self.dimension = embedding.dimension

    def count_tokens(self, text: str) -> int:
        return self.embedding.count_tokens(text)

    def count_query_tokens(self, text: str) -> int:
        try:
            return self.embedding.count_query_tokens(text)
        except QueryEmbeddingUnavailableError:
            raise
        except EmbeddingRuntimeUnavailableError as exc:
            raise QueryEmbeddingUnavailableError(
                "The local query tokenizer runtime is unavailable."
            ) from exc

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return self.embedding.encode_documents(texts)

    def encode_query(self, text: str) -> list[float]:
        try:
            return self.embedding.encode_query(text)
        except QueryEmbeddingUnavailableError:
            raise
        except EmbeddingRuntimeUnavailableError as exc:
            raise QueryEmbeddingUnavailableError(
                "The local query embedding runtime is unavailable."
            ) from exc
