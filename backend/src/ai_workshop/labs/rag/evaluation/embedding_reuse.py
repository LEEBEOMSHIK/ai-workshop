"""Bounded completed values for one frozen evaluation claim, never shared runtimes."""

import math
import sys
from collections.abc import Callable, Sequence
from typing import Literal, cast

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingValidationError
from ai_workshop.labs.rag.executions.operation_timings import measure_operation
from ai_workshop.labs.rag.search.configuration_port import OwnedEmbeddingPort

type _Method = Literal["query_tokens", "document_tokens", "query", "documents"]
type _Key = tuple[str, int, _Method, tuple[str, ...]]
type _Vector = tuple[float, ...]
type _Value = int | _Vector | tuple[_Vector, ...]
_MISSING = object()


def _size(value: object) -> int:
    # Count repeated references repeatedly: conservative, including retained input strings.
    return sys.getsizeof(value) + (sum(_size(item) for item in value)
                                  if isinstance(value, tuple) else 0)


class FrozenEmbeddingResults:
    def __init__(self, max_bytes: int) -> None:
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError("Embedding result budget must be a nonnegative integer.")
        self._max_bytes = max_bytes
        self._bytes = 0
        self._values: dict[_Key, _Value] = {}
        self._closed = False

    def bound(
        self, *, namespace: str, factory: Callable[[], OwnedEmbeddingPort], dimension: int,
    ) -> OwnedEmbeddingPort:
        self._check_open()
        if not isinstance(namespace, str) or not namespace or type(dimension) is not int:
            raise ValueError("Invalid frozen embedding namespace or dimension.")
        if dimension < 1:
            raise ValueError("Invalid frozen embedding dimension.")
        return _BoundEmbedding(self, namespace, factory, dimension)

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("Frozen embedding results are closed.")

    def _admit(self, key: _Key, value: _Value) -> None:
        self._check_open()
        if key in self._values:
            return
        # 512 bytes per entry covers dict slots, growth slack and bookkeeping; additionally
        # include empty dict size on each entry, overcounting rather than undercounting it.
        size = _size(key) + _size(value) + 512 + sys.getsizeof({})
        if size <= self._max_bytes - self._bytes:
            self._values[key] = value
            self._bytes += size

    def close(self) -> None:
        self._closed = True
        self._values.clear()
        self._bytes = 0


class _BoundEmbedding:
    def __init__(
        self, store: FrozenEmbeddingResults, namespace: str,
        factory: Callable[[], OwnedEmbeddingPort], dimension: int,
    ) -> None:
        self.dimension = dimension
        self._store = store
        self._namespace = namespace
        self._factory: Callable[[], OwnedEmbeddingPort] | None = factory
        self._delegate: OwnedEmbeddingPort | None = None
        self._closed = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        delegate, self._delegate = self._delegate, None
        self._factory = None
        if delegate is not None:
            delegate.close()

    def _runtime(self) -> OwnedEmbeddingPort:
        if self._delegate is None:
            if self._factory is None:
                raise RuntimeError("Frozen embedding execution is closed.")
            delegate = self._factory()
            if delegate.dimension != self.dimension:
                delegate.close()
                raise EmbeddingValidationError("Embedding runtime dimension changed.")
            self._delegate = delegate
        return self._delegate

    def _value(self, method: _Method, inputs: tuple[str, ...]) -> _Value:
        if self._closed:
            raise RuntimeError("Frozen embedding execution is closed.")
        self._store._check_open()
        if any(not isinstance(text, str) for text in inputs):
            raise EmbeddingValidationError("Embedding inputs must be strings.")
        key = (self._namespace, self.dimension, method, inputs)
        found = self._store._values.get(key, _MISSING)
        if found is not _MISSING:
            items = len(inputs) if method == "documents" else 1
            with measure_operation("embedding.result_reuse", items=items, reused_items=items):
                return cast(_Value, found)
        delegate = self._runtime()
        value: _Value
        if method in ("query_tokens", "document_tokens"):
            count = (delegate.count_query_tokens(inputs[0]) if method == "query_tokens"
                     else delegate.count_tokens(inputs[0]))
            if type(count) is not int or count < 0:
                raise EmbeddingValidationError("Embedding token count must be nonnegative integer.")
            value = count
        elif method == "query":
            value = self._vector(delegate.encode_query(inputs[0]))
        else:
            vectors = delegate.encode_documents(inputs)
            if (not isinstance(vectors, Sequence) or isinstance(vectors, (str, bytes))
                    or len(vectors) != len(inputs)):
                raise EmbeddingValidationError("Embedding output count differs from input count.")
            value = tuple(self._vector(vector) for vector in vectors)
        self._store._admit(key, value)
        return value

    def _vector(self, raw: object) -> _Vector:
        if (not isinstance(raw, Sequence) or isinstance(raw, (str, bytes))
                or len(raw) != self.dimension
                or any(type(value) not in (int, float) for value in raw)):
            raise EmbeddingValidationError("Invalid embedding vector shape or values.")
        try:
            result = tuple(float(value) for value in raw)
        except (ValueError, OverflowError):
            raise EmbeddingValidationError("Invalid embedding vector values.") from None
        if not all(math.isfinite(value) for value in result):
            raise EmbeddingValidationError("Embedding values must be finite.")
        norm = math.sqrt(sum(value * value for value in result))
        if not math.isclose(norm, 1.0, rel_tol=1e-5, abs_tol=1e-5):
            raise EmbeddingValidationError("Embedding vectors must be normalized.")
        return result

    def count_tokens(self, text: str) -> int:
        return cast(int, self._value("document_tokens", (text,)))

    def count_query_tokens(self, text: str) -> int:
        return cast(int, self._value("query_tokens", (text,)))

    def encode_query(self, text: str) -> list[float]:
        return list(cast(_Vector, self._value("query", (text,))))

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, (str, bytes)):
            raise EmbeddingValidationError("Document inputs must be a sequence of strings.")
        return [list(vector) for vector in
                cast(tuple[_Vector, ...], self._value("documents", tuple(texts)))]
