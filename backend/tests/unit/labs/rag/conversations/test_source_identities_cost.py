"""Preserve source discovery while making scalar width cheap to traverse."""

import cProfile
from collections.abc import Callable
from copy import deepcopy
from types import CodeType
from uuid import UUID

import pytest

from ai_workshop.labs.rag.conversations import access

type Identity = tuple[UUID, UUID, UUID]
KEYS = ("document_id", "asset_version_id", "projection_id")


def source(start: int = 1) -> dict[str, object]:
    return {key: str(UUID(int=start + index)) for index, key in enumerate(KEYS)}


def reference(value: object) -> set[Identity]:
    """The prior walker is an oracle for ordering, parsing and accepted shapes."""
    result: set[Identity] = set()
    if isinstance(value, dict):
        if all(key in value for key in KEYS):
            result.add((
                UUID(str(value["document_id"])),
                UUID(str(value["asset_version_id"])),
                UUID(str(value["projection_id"])),
            ))
        for child in value.values():
            result.update(reference(child))
    elif isinstance(value, list):
        for child in value:
            result.update(reference(child))
    return result


@pytest.mark.parametrize(
    "value",
    [
        None, False, 17, "text", b"text", (), (source(),),
        {}, [], source(),
        {key: UUID(int=index + 1) for index, key in enumerate(KEYS)},
        {"document_id": "not-a-uuid", "child": [source()]},
        {"diagnostics": {"candidates": [{"source": source()}]}},
        {**source(), "children": [source(4), {"nested": source(7)}]},
        [source(), source(), {"wrapped": [source(4), source()]}],
    ],
)
def test_nested_shapes_match_prior_walker_without_mutating_input(value: object) -> None:
    before = deepcopy(value)
    assert access.source_identities(value) == reference(value)
    assert value == before


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("bad", [None, "bad-uuid"])
def test_complete_malformed_sources_keep_original_exception(key: str, bad: object) -> None:
    value = {"nested": [{**source(), key: bad}]}
    with pytest.raises(ValueError) as previous:
        reference(value)
    with pytest.raises(ValueError) as actual:
        access.source_identities(value)
    assert str(actual.value) == str(previous.value)


class LoggedValue:
    def __init__(self, label: str, text: str, events: list[str]) -> None:
        self.label, self.text, self.events = label, text, events

    def __str__(self) -> str:
        self.events.append(self.label)
        return self.text


def logged_tree(events: list[str], invalid: str | None) -> dict[str, object]:
    def row(name: str, start: int) -> dict[str, object]:
        return {
            key: LoggedValue(
                f"{name}.{key}",
                "invalid" if f"{name}.{key}" == invalid else str(UUID(int=start + index)),
                events,
            )
            for index, key in enumerate(KEYS)
        }

    return {
        **row("parent", 1),
        "children": [row("first", 4), {"nested": row("second", 7)}],
        "last": row("last", 10),
    }


@pytest.mark.parametrize("invalid", [None, "parent.asset_version_id", "first.projection_id"])
def test_parent_uuid_order_and_depth_first_parsing_match_prior_walker(
    invalid: str | None,
) -> None:
    previous_events: list[str] = []
    actual_events: list[str] = []
    previous_tree = logged_tree(previous_events, invalid)
    actual_tree = logged_tree(actual_events, invalid)
    if invalid is None:
        assert access.source_identities(actual_tree) == reference(previous_tree)
        assert actual_events == [
            f"{name}.{key}" for name in ("parent", "first", "second", "last") for key in KEYS
        ]
    else:
        with pytest.raises(ValueError):
            reference(previous_tree)
        with pytest.raises(ValueError):
            access.source_identities(actual_tree)
    assert actual_events == previous_events


def test_repeated_shared_child_is_parsed_each_time_and_deduplicated() -> None:
    events: list[str] = []
    shared = {
        key: LoggedValue(key, str(UUID(int=index + 1)), events)
        for index, key in enumerate(KEYS)
    }
    assert access.source_identities([shared, shared]) == reference(source())
    assert events == list(KEYS) * 2


def test_calls_return_independent_sets_and_reparse_changed_input() -> None:
    value = source()
    first = access.source_identities(value)
    second = access.source_identities(value)
    assert first == second and first is not second
    first.clear()
    assert second == reference(value)
    value["projection_id"] = str(UUID(int=90))
    assert access.source_identities(value) == reference(value)
    assert access.source_identities(value) != second


@pytest.mark.parametrize("container", ["dict", "list"])
def test_cycles_keep_recursion_error_instead_of_being_skipped(container: str) -> None:
    value: dict[str, object] | list[object]
    if container == "dict":
        value = {}
        value["self"] = value
    else:
        value = []
        value.append(value)
    with pytest.raises(RecursionError):
        reference(value)
    with pytest.raises(RecursionError):
        access.source_identities(value)


def walker_calls(value: object) -> int:
    profiler = cProfile.Profile()
    profiler.runcall(access.source_identities, value)
    filename = access.source_identities.__code__.co_filename
    return sum(
        item.callcount for item in profiler.getstats()
        if isinstance(item.code, CodeType) and item.code.co_filename == filename
    )


def test_scalar_width_does_not_increase_python_walker_calls() -> None:
    small = {"values": [0]}
    wide = {"values": [0] * 4096}
    assert walker_calls(wide) == walker_calls(small)


def test_walk_uses_one_result_set_regardless_of_scalar_width(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    allocations: list[None] = []
    original: Callable[[], set[Identity]] = set

    def counted_set() -> set[Identity]:
        allocations.append(None)
        return original()

    monkeypatch.setattr(access, "set", counted_set, raising=False)
    assert access.source_identities({"values": [0] * 4096}) == set()
    assert len(allocations) == 1
