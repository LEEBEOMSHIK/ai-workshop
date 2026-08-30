import hashlib
import math
from collections.abc import Sequence


class DeterministicFakeEmbedding:
    def __init__(
        self,
        *,
        dimension: int,
        query_prefix: str = "query: ",
        document_prefix: str = "passage: ",
    ) -> None:
        if dimension < 1:
            raise ValueError("The fake embedding dimension must be positive.")
        self.dimension = dimension
        self.query_prefix = query_prefix
        self.document_prefix = document_prefix

    def count_tokens(self, text: str) -> int:
        return len(f"{self.document_prefix}{text}".split())

    def count_query_tokens(self, text: str) -> int:
        return len(f"{self.query_prefix}{text}".split())

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._encode(f"{self.document_prefix}{text}") for text in texts]

    def encode_query(self, text: str) -> list[float]:
        return self._encode(f"{self.query_prefix}{text}")

    def _encode(self, text: str) -> list[float]:
        tokens = text.split() or ["<empty>"]
        vector = [0.0] * self.dimension
        for ordinal, token in enumerate(tokens):
            digest = hashlib.sha256(f"{ordinal}:{token}".encode()).digest()
            first = int.from_bytes(digest[:4], "big") % self.dimension
            second = int.from_bytes(digest[4:8], "big") % self.dimension
            vector[first] += 1.0 if digest[8] & 1 else -1.0
            vector[second] += (digest[9] + 1) / 256.0
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            vector[0] = 1.0
            norm = 1.0
        return [value / norm for value in vector]
