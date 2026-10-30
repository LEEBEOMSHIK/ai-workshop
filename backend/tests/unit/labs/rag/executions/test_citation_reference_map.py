"""Request-local citation identity metadata survives private trace lifecycle changes."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions import agent_trace as trace_module
from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    AgentSpan,
    AgentTraceCollector,
    capture_agent_trace,
    current_agent_trace,
    next_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
    response_agent_trace,
    storage_agent_trace,
)
from ai_workshop.labs.rag.executions.observer import current_observer


def reference_map(ids=None):
    factory = getattr(trace_module, "CitationReferenceMap", None)
    assert factory is not None, "CitationReferenceMap is required for reversible v6 traces"
    return factory(evidence_ids=(uuid4(), uuid4()) if ids is None else ids)


def model_span(**fields):
    return AgentSpan(
        id=uuid4(), parent_id=None, sequence=0, kind="model", name="chat_completion",
        state="running", started_at=datetime.now(UTC), **fields,
    )


def test_legacy_span_without_reference_metadata_reads_as_none():
    legacy = model_span().model_dump(mode="json")
    legacy.pop("citation_reference_map", None)
    restored = AgentSpan.model_validate(legacy)
    assert getattr(restored, "citation_reference_map", "missing") is None


def test_reference_map_preserves_exact_order_and_is_frozen():
    ids = (UUID(int=9), UUID(int=3))
    value = reference_map(ids)
    assert value.format == "rag-answer-v6"
    assert value.evidence_ids == ids
    assert value.model_dump(mode="json")["evidence_ids"] == [str(item) for item in ids]
    with pytest.raises(ValidationError, match="frozen"):
        value.evidence_ids = tuple(reversed(ids))


@pytest.mark.parametrize("size", [0, 1, 200])
def test_reference_map_accepts_bounded_unique_ids(size):
    ids = tuple(UUID(int=i + 1) for i in range(size))
    assert reference_map(ids).evidence_ids == ids


@pytest.mark.parametrize("invalid", ["duplicates", "oversized", "invalid_uuid"])
def test_reference_map_rejects_ambiguous_or_unbounded_values(invalid):
    ids = {
        "duplicates": (UUID(int=1), UUID(int=1)),
        "oversized": tuple(UUID(int=i + 1) for i in range(201)),
        "invalid_uuid": ("e1",),
    }[invalid]
    with pytest.raises(ValidationError):
        reference_map(ids)


@pytest.mark.parametrize("field,value", [("format", "rag-answer-v5"), ("unexpected", 1)])
def test_reference_map_contract_is_closed(field, value):
    factory = type(reference_map())
    with pytest.raises(ValidationError):
        factory.model_validate({"evidence_ids": [], field: value})


@pytest.mark.parametrize("kind", ["agent", "delegation", "tool"])
def test_only_model_spans_can_have_reference_metadata(kind):
    values = model_span().model_dump()
    values.update(kind=kind, citation_reference_map=reference_map())
    with pytest.raises(ValidationError, match="model"):
        AgentSpan.model_validate(values)


async def mapped_trace(*, capture=True):
    mapping = reference_map()
    collector = AgentTraceCollector()
    with capture_agent_trace(capture):
        root = await collector.start_span(kind="agent", name="answer_specialist")
        model = await collector.start_span(
            kind="model", name="chat_completion", parent_id=root,
            input='{"evidence_ref":"e1","text":"synthetic source"}',
            citation_reference_map=mapping,
        )
        trace = current_agent_trace()
        assert trace is not None
    return collector, model, trace, mapping


async def test_first_published_model_snapshot_contains_reference_metadata():
    class Observer:
        complete = True

        def __init__(self):
            self.snapshots = []

        async def record_agent_trace(self, trace):
            self.snapshots.append(trace)

    observer = Observer()
    token = current_observer.set(observer)
    try:
        _, _, trace, mapping = await mapped_trace()
    finally:
        current_observer.reset(token)
    assert len(observer.snapshots) == 2
    assert observer.snapshots[0].spans[0].citation_reference_map is None
    assert observer.snapshots[1] == trace
    assert trace.spans[1].state == "running"
    assert trace.spans[1].citation_reference_map == mapping


@pytest.mark.parametrize("state", ["failed", "cancelled", "completed"])
async def test_reference_metadata_survives_terminal_and_json_storage(state):
    collector, model, initial, mapping = await mapped_trace()
    with capture_agent_trace(True):
        if state == "completed":
            await collector.end_span(model, output='{"evidence_ids":["e1"]}')
            await collector.finish(state="completed")
        else:
            await collector.finish(state=state, error_code="cancelled" if state == "cancelled"
                                   else "provider_invalid_response")
        trace = current_agent_trace()
        assert trace is not None
        rejected = response_agent_trace(answer_validated=False)
    stored = next_agent_trace(initial.model_dump(mode="json"), trace)
    restored = read_agent_trace({TRACE_STORAGE_KEY: stored})
    assert restored is not None
    assert restored.spans[1].state == state
    assert restored.spans[1].citation_reference_map == mapping
    assert rejected is not None and rejected.spans[1].citation_reference_map == mapping
    await collector.end_span(model, output="late value")
    assert collector.spans[1] == trace.spans[1]


@pytest.mark.parametrize("capture", [False, True])
async def test_metadata_only_copy_preserves_mapping_without_bodies(capture):
    _, _, trace, mapping = await mapped_trace(capture=capture)
    stored = storage_agent_trace(persisted_agent_trace(trace))
    assert stored.content_retention == "metadata_only"
    assert stored.spans[1].citation_reference_map == mapping
    assert stored.spans[1].input.text is None
    assert "synthetic source" not in stored.model_dump_json()


@pytest.mark.parametrize("change", ["remove", "reorder", "replace", "late_add"])
async def test_running_reference_metadata_cannot_be_rewritten(change):
    _, _, trace, mapping = await mapped_trace()
    before = trace
    replacement = None
    if change == "reorder":
        replacement = reference_map(tuple(reversed(mapping.evidence_ids)))
    elif change == "replace":
        replacement = reference_map()
    elif change == "late_add":
        before = trace.model_copy(update={"spans": (
            trace.spans[0], trace.spans[1].model_copy(update={"citation_reference_map": None}),
        )})
        replacement = mapping
    changed = trace.model_copy(update={
        "revision": trace.revision + 1,
        "spans": (trace.spans[0], trace.spans[1].model_copy(update={
            "citation_reference_map": replacement,
        })),
    })
    with pytest.raises(ValueError, match="reference map"):
        next_agent_trace(before.model_dump(mode="json"), changed)


async def test_storage_revalidates_forged_nested_reference_metadata():
    _, _, trace, mapping = await mapped_trace()
    forged_map = mapping.model_copy(update={"evidence_ids": (UUID(int=1), UUID(int=1))})
    forged = trace.model_copy(update={"spans": (
        trace.spans[0], trace.spans[1].model_copy(update={"citation_reference_map": forged_map}),
    )})
    with pytest.raises(ValidationError):
        storage_agent_trace(forged)


@pytest.mark.parametrize("state", ["failed", "cancelled", "completed"])
async def test_terminal_reference_metadata_cannot_be_rewritten(state):
    collector, _, _, _ = await mapped_trace()
    with capture_agent_trace(True):
        await collector.finish(state=state)
        trace = current_agent_trace()
    assert trace is not None
    changed = trace.model_copy(update={
        "revision": trace.revision + 1,
        "spans": (trace.spans[0], trace.spans[1].model_copy(update={
            "citation_reference_map": reference_map(),
        })),
    })
    with pytest.raises(ValueError, match="reference map"):
        next_agent_trace(trace.model_dump(mode="json"), changed)


async def test_reference_metadata_is_isolated_between_collectors():
    _, _, first, first_map = await mapped_trace()
    _, _, second, second_map = await mapped_trace()
    assert first_map != second_map
    assert first.spans[1].citation_reference_map == first_map
    assert second.spans[1].citation_reference_map == second_map
