"""Independent result-cache boundaries; synthetic inputs and no model/network."""

import gc
import weakref
from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.evaluation.embedding_reuse import FrozenEmbeddingResults
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.evaluation.test_frozen_embedding_lifetime_independent import (
    prepared_harness,
)


class SyntheticPort:
    dimension = 2

    def __init__(self):
        self.calls = []
        self.closed = False
        self.invalid = False

    def count_tokens(self, text):
        self.calls.append(("document_tokens", text))
        return len(text)

    def count_query_tokens(self, text):
        self.calls.append(("query_tokens", text))
        return len(text) + 1

    def encode_query(self, text):
        self.calls.append(("query", text))
        return [1.0, 0.0]

    def encode_documents(self, texts):
        self.calls.append(("documents", tuple(texts)))
        if self.invalid:
            return [[1.0, 0.0], [float("nan"), 0.0]]
        return [[1.0, 0.0] if index % 2 == 0 else [0.0, 1.0]
                for index, _ in enumerate(texts)]

    def close(self):
        self.closed = True


def test_exact_batches_do_not_rebatch_partial_hits_or_share_mutable_returns():
    store = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    port = SyntheticPort()
    bound = store.bound(namespace="fixed", factory=lambda: port, dimension=2)
    first = bound.encode_documents(["alpha", "beta"])
    first[0][0] = -99
    assert bound.encode_documents(["alpha", "beta"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert bound.encode_documents(["beta", "alpha"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert bound.encode_documents(["alpha", "alpha", "beta"]) == [
        [1.0, 0.0], [0.0, 1.0], [1.0, 0.0],
    ]
    assert port.calls == [
        ("documents", ("alpha", "beta")),
        ("documents", ("beta", "alpha")),
        ("documents", ("alpha", "alpha", "beta")),
    ]
    bound.close()
    store.close()


@pytest.mark.parametrize("budget", [0, 1, 512])
def test_small_budget_recomputes_without_changing_calls_or_output(budget):
    store = FrozenEmbeddingResults(max_bytes=budget)
    port = SyntheticPort()
    bound = store.bound(namespace="fixed", factory=lambda: port, dimension=2)
    for _ in range(3):
        assert bound.encode_documents(["alpha", "beta"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert port.calls == [("documents", ("alpha", "beta"))] * 3
    bound.close()
    store.close()


def test_closing_one_execution_does_not_close_another_runtime():
    store = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    first, second = SyntheticPort(), SyntheticPort()
    one = store.bound(namespace="fixed", factory=lambda: first, dimension=2)
    two = store.bound(namespace="fixed", factory=lambda: second, dimension=2)
    one.encode_query("alpha")
    two.encode_query("beta")
    one.close()
    assert first.closed and not second.closed
    assert two.encode_query("alpha") == [1.0, 0.0]
    assert second.calls == [("query", "beta")]
    two.close()
    assert second.closed
    store.close()


@pytest.mark.parametrize("changed", ["actor", "case", "model", "source"])
async def test_adapter_namespace_separates_actual_cached_values(changed):
    from tests.unit.labs.rag.evaluation.test_frozen_embedding_reuse_wiring import (
        ACTOR_ID,
        adapter_harness,
    )

    store = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    adapter, candidate, case, _, factory, _, _ = adapter_harness(results=store)
    factory.side_effect = SyntheticPort

    async def compute(actor):
        prepared = await adapter.prepare(actor, candidate, case)
        bound = prepared.configuration.request_owned_embedding_factory()
        assert bound.encode_query("same synthetic input") == [1.0, 0.0]
        bound.close()

    await compute(ACTOR_ID)
    await compute(ACTOR_ID)
    assert factory.call_count == 1
    actor = ACTOR_ID
    if changed == "actor":
        actor = uuid4()
    elif changed == "case":
        case.id = uuid4()
    elif changed == "model":
        candidate.component_snapshot["models"][0]["config"]["revision"] = "b" * 40
    else:
        candidate.execution_snapshot["sources"][0]["chunk_text"] += " new"
    await compute(actor)
    assert factory.call_count == 2
    store.close()


def test_failed_batch_is_not_published_and_token_namespaces_are_separate():
    store = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    port = SyntheticPort()
    bound = store.bound(namespace="fixed", factory=lambda: port, dimension=2)
    port.invalid = True
    with pytest.raises(EmbeddingValidationError):
        bound.encode_documents(["alpha", "beta"])
    port.invalid = False
    assert bound.encode_documents(["alpha", "beta"]) == [[1.0, 0.0], [0.0, 1.0]]
    assert len(port.calls) == 2
    assert bound.count_tokens("alpha") == 5
    assert bound.count_query_tokens("alpha") == 6
    assert bound.count_tokens("alpha") == 5
    assert bound.count_query_tokens("alpha") == 6
    assert len(port.calls) == 4
    bound.close()
    store.close()


def test_completed_values_do_not_retain_delegate_and_new_claim_starts_empty():
    store = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    references = []

    def factory():
        port = SyntheticPort()
        references.append(weakref.ref(port))
        return port

    first = store.bound(namespace="fixed", factory=factory, dimension=2)
    assert first.encode_query("alpha") == [1.0, 0.0]
    first.close()
    gc.collect()
    assert references[0]() is None
    second = store.bound(namespace="fixed", factory=factory, dimension=2)
    assert second.encode_query("alpha") == [1.0, 0.0]
    assert len(references) == 1
    second.close()
    store.close()
    with pytest.raises(RuntimeError, match="closed"):
        second.encode_query("alpha")
    fresh = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    third = fresh.bound(namespace="fixed", factory=factory, dimension=2)
    third.encode_query("alpha")
    assert len(references) == 2
    third.close()
    fresh.close()


async def test_warm_cache_does_not_bypass_current_frozen_access(tmp_path):
    service, prepared, factory, runtime, validations = await prepared_harness(tmp_path)
    store = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    configuration = replace(
        prepared.configuration,
        request_owned_embedding_factory=lambda: store.bound(
            namespace="fixed-authorized-synthetic", factory=factory, dimension=2,
        ),
    )
    prepared = replace(prepared, configuration=configuration)
    first = await service.execute(prepared)
    assert first.generation.text == "synthetic fact"
    assert validations and len(runtime.requests) == 1
    assert len(factory.adapters) == 1
    second = await service.execute(prepared)
    assert second.grounding_evidence == first.grounding_evidence
    assert second.generation.citations == first.generation.citations
    assert len(factory.adapters) == 1

    async def revoked(identities):
        assert identities
        raise AppError("not_found", "The frozen sources are no longer available.", 404)

    denied = replace(prepared, frozen_access=revoked)
    with pytest.raises(AppError, match="no longer available"):
        await service.execute(denied)
    assert len(factory.adapters) == 1
    assert len(runtime.requests) == 2
    assert all(ref() is None for ref in factory.models)
    store.close()
