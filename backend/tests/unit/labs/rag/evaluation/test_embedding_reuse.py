"""Offline contracts for claim-local results, never model lifetime extension."""

import asyncio
import gc
import weakref
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import pytest

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingValidationError
from ai_workshop.labs.rag.evaluation.embedding_reuse import FrozenEmbeddingResults


class Fake:
    dimension = 2

    def __init__(self) -> None:
        self.calls: list[Any] = []
        self.closed = 0
        self.bad: Any = None

    def close(self) -> None:
        self.closed += 1

    def count_tokens(self, text: str) -> int:
        self.calls.append(("document_tokens", text))
        return len(text)

    def count_query_tokens(self, text: str) -> int:
        self.calls.append(("query_tokens", text))
        return len(text) + 1

    def encode_query(self, text: str) -> list[float]:
        self.calls.append(("query", text))
        return [1.0, 0.0] if self.bad is None else self.bad

    def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(("documents", tuple(texts)))
        return ([[1.0, 0.0] if i % 2 == 0 else [0.0, 1.0]
                 for i, _ in enumerate(texts)] if self.bad is None else self.bad)


def test_all_four_results_reuse_without_constructing_second_runtime() -> None:
    cache = FrozenEmbeddingResults(100_000)
    fake = Fake()
    first = cache.bound(namespace="claim", factory=lambda: fake, dimension=2)
    assert fake.calls == []
    assert first.count_tokens("hi") == 2
    assert first.count_query_tokens("hi") == 3
    assert first.encode_query("hi") == [1.0, 0.0]
    assert first.encode_documents(["hi", "hi"]) == [[1.0, 0.0], [0.0, 1.0]]
    first.close()
    def forbidden() -> Fake:
        raise AssertionError("runtime must stay unloaded on a hit")
    second = cache.bound(namespace="claim", factory=forbidden, dimension=2)
    assert second.count_tokens("hi") == 2
    assert second.count_query_tokens("hi") == 3
    assert second.encode_query("hi") == [1.0, 0.0]
    values = second.encode_documents(["hi", "hi"])
    values[0][0] = 123
    assert second.encode_documents(["hi", "hi"])[0] == [1.0, 0.0]
    second.close()
    assert fake.closed == 1


def test_exact_batch_order_partial_overlap_and_namespace_never_rebatch() -> None:
    cache = FrozenEmbeddingResults(100_000)
    fake = Fake()
    wrapper = cache.bound(namespace="a", factory=lambda: fake, dimension=2)
    for batch in (["a", "b"], ["b", "a"], ["a"], ["a", "a"], []):
        wrapper.encode_documents(batch)
    assert fake.calls == [("documents", tuple(b)) for b in
                          (["a", "b"], ["b", "a"], ["a"], ["a", "a"], [])]
    other = cache.bound(namespace="b", factory=lambda: Fake(), dimension=2)
    assert other.encode_documents(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.parametrize("budget", [0, 1, 64])
def test_small_budget_bypasses_admission(budget: int) -> None:
    cache = FrozenEmbeddingResults(budget)
    fake = Fake()
    wrapper = cache.bound(namespace="a", factory=lambda: fake, dimension=2)
    wrapper.encode_query("x")
    wrapper.encode_query("x")
    assert len(fake.calls) == 2


@pytest.mark.parametrize("bad", [[1.0], [float("nan"), 0.0], [2.0, 0.0], [True, 0]])
def test_invalid_vector_not_admitted(bad: Any) -> None:
    cache = FrozenEmbeddingResults(100_000)
    fake = Fake()
    fake.bad = bad
    wrapper = cache.bound(namespace="a", factory=lambda: fake, dimension=2)
    with pytest.raises(EmbeddingValidationError):
        wrapper.encode_query("x")
    fake.bad = None
    assert wrapper.encode_query("x") == [1.0, 0.0]
    assert len(fake.calls) == 2


def test_invalid_batch_does_not_partially_publish() -> None:
    cache = FrozenEmbeddingResults(100_000)
    fake = Fake()
    fake.bad = [[1.0, 0.0], [2.0, 0.0]]
    wrapper = cache.bound(namespace="a", factory=lambda: fake, dimension=2)
    with pytest.raises(EmbeddingValidationError):
        wrapper.encode_documents(["a", "b"])
    fake.bad = None
    assert wrapper.encode_documents(["a", "b"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert len(fake.calls) == 2


def test_close_rejects_late_hits_and_store_close_clears_all_wrappers() -> None:
    cache = FrozenEmbeddingResults(100_000)
    fake = Fake()
    wrapper = cache.bound(namespace="a", factory=lambda: fake, dimension=2)
    wrapper.encode_query("x")
    wrapper.close()
    wrapper.close()
    with pytest.raises(RuntimeError):
        wrapper.encode_query("x")
    fresh = cache.bound(namespace="a", factory=lambda: Fake(), dimension=2)
    cache.close()
    cache.close()
    with pytest.raises(RuntimeError):
        fresh.encode_query("x")
    with pytest.raises(RuntimeError):
        cache.bound(namespace="a", factory=lambda: Fake(), dimension=2)


@pytest.mark.parametrize("budget", [-1, True, 1.5])
def test_invalid_budget_rejected(budget: Any) -> None:
    with pytest.raises(ValueError):
        FrozenEmbeddingResults(budget)


def test_close_drops_runtime_and_capturing_factory_references() -> None:
    cache = FrozenEmbeddingResults(100_000)
    fake = Fake()
    pointer = weakref.ref(fake)
    wrapper = cache.bound(namespace="a", factory=lambda held=fake: held, dimension=2)
    wrapper.encode_query("x")
    del fake
    wrapper.close()
    gc.collect()
    assert pointer() is None


@pytest.mark.parametrize("bad", [-1, True, 2.5])
def test_invalid_token_counts_never_cached(bad: Any) -> None:
    class InvalidCount(Fake):
        def count_tokens(self, text: str) -> int:
            return bad  # type: ignore[no-any-return]
    cache = FrozenEmbeddingResults(100_000)
    wrapper = cache.bound(namespace="a", factory=InvalidCount, dimension=2)
    with pytest.raises(EmbeddingValidationError):
        wrapper.count_tokens("x")
    wrapper.close()
    fresh = cache.bound(namespace="a", factory=Fake, dimension=2)
    assert fresh.count_tokens("x") == 1


@pytest.mark.parametrize("failure", [RuntimeError("unavailable"), asyncio.CancelledError()])
def test_delegate_failures_never_publish(failure: BaseException) -> None:
    class Failing(Fake):
        def encode_documents(self, texts: Sequence[str]) -> list[list[float]]:
            raise failure
    cache = FrozenEmbeddingResults(100_000)
    first = cache.bound(namespace="a", factory=Failing, dimension=2)
    with pytest.raises(type(failure)):
        first.encode_documents(["x"])
    first.close()
    second = cache.bound(namespace="a", factory=Fake, dimension=2)
    assert second.encode_documents(["x"]) == [[1.0, 0.0]]


def test_only_real_hits_emit_separate_reuse_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    from ai_workshop.labs.rag.evaluation import embedding_reuse
    observed = []

    @contextmanager
    def measure(name: str, *, items: int, reused_items: int) -> Iterator[None]:
        observed.append((name, items, reused_items))
        yield

    monkeypatch.setattr(embedding_reuse, "measure_operation", measure)
    cache = FrozenEmbeddingResults(100_000)
    first = cache.bound(namespace="a", factory=Fake, dimension=2)
    first.encode_documents(["a", "b"])
    first.count_tokens("x")
    assert observed == []
    first.close()
    second = cache.bound(namespace="a", factory=Fake, dimension=2)
    second.encode_documents(["a", "b"])
    second.count_tokens("x")
    assert observed == [("embedding.result_reuse", 2, 2), ("embedding.result_reuse", 1, 1)]


def test_long_private_keys_are_counted_in_admission_budget() -> None:
    fake = Fake()
    cache = FrozenEmbeddingResults(2000)
    wrapper = cache.bound(namespace="a", factory=lambda: fake, dimension=2)
    wrapper.encode_query("x" * 3000)
    wrapper.encode_query("x" * 3000)
    assert len(fake.calls) == 2
    assert cache._bytes == 0 and not cache._values
