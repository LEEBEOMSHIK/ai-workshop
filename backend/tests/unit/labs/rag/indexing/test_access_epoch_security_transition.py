"""Whole synthetic maps remain exhaustive across main-security creation."""

import importlib
import json
from dataclasses import replace
from typing import Any

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import _canonical
from tests.unit.labs.rag.indexing import test_access_epoch_security_inventory as wire

MODULE = "ai_workshop.labs.rag.indexing.access_epoch_security_transition"


def case() -> tuple[bytes, bytes, Any]:
    state, stats, descriptor = wire.sample()
    main = wire.decode(state, stats, descriptor)
    original = dict(state["metadata"]["indices"])
    del original[wire.NAME]
    return _canonical(original), _canonical(state["metadata"]["indices"]), main


def verify(
    original: bytes, current: bytes, bootstrap: Any, final: Any = None, after: bytes | None = None
) -> None:
    def state(value: bytes) -> bytes:
        return _canonical({"metadata": {"indices": json.loads(value)}})

    importlib.import_module(MODULE).require_main_security_transition(
        state(original),
        state(current),
        bootstrap,
        final_state=state(after or current) if final is not None else None,
        final=final,
    )


def test_full_original_union_exact_main_and_final_equal_bootstrap() -> None:
    original, current, bootstrap = case()
    verify(original, current, bootstrap)
    verify(original, current, bootstrap, replace(bootstrap, deleted_docs=91))


@pytest.mark.parametrize(
    "fault",
    [
        "old_private",
        "old_alias",
        "old_uuid",
        "old_missing",
        "extra_row",
        "system",
        "already_main",
        "already_alias",
        "duplicate_uuid",
        "bool_system",
        "bool_count",
        "main_private",
        "main_map",
        "schema",
        "count_kind",
        "unknown_field",
        "final_old",
        "final_main",
        "final_count",
        "final_uuid",
        "main_name",
    ],
)
def test_no_dropped_changed_or_unproved_physical_row(fault: str) -> None:
    original, current, bootstrap = case()
    old = json.loads(original)
    before = json.loads(current)
    final = None
    after = None
    name = next(iter(old))
    if fault in {"old_private", "old_alias", "old_uuid", "old_missing"}:
        if fault == "old_private":
            before[name]["settings"]["private-extra"] = "changed"
        elif fault == "old_alias":
            before[name]["aliases"] = ["changed-alias"]
        elif fault == "old_uuid":
            before[name]["settings"]["index.uuid"] = "changedUuid"
        else:
            del before[name]
        current = _canonical(before)
    elif fault == "extra_row":
        before["added"] = dict(before[name])
        before["added"]["settings"] = {**before[name]["settings"], "index.uuid": "addedUuid"}
        current = _canonical(before)
    elif fault in {"system", "bool_system", "already_alias", "unknown_field"}:
        if fault == "system":
            old[name]["system"] = True
        elif fault == "bool_system":
            old[name]["system"] = 0
        elif fault == "already_alias":
            old[name]["aliases"] = [".security"]
        else:
            old[name]["unknown"] = "value"
        original = _canonical(old)
    elif fault == "already_main":
        original = current
    elif fault == "duplicate_uuid":
        before[name]["settings"]["index.uuid"] = bootstrap.uuid
        current = _canonical(before)
    elif fault == "bool_count":
        bootstrap = replace(bootstrap, count=True)
    elif fault == "main_private":
        bootstrap = replace(bootstrap, private_metadata=_canonical({wire.NAME: old[name]}))
    elif fault == "main_map":
        bootstrap = replace(bootstrap, private_physical_inventory=original)
    elif fault == "schema":
        bootstrap = replace(bootstrap, schema="unknown")
    elif fault == "count_kind":
        bootstrap = replace(bootstrap, count_kind="logical_docs")
    elif fault == "main_name":
        bootstrap = replace(bootstrap, name=".security-tokens")
    else:
        final = replace(bootstrap)
        if fault == "final_old":
            before[name]["settings"]["changed"] = "private"
            after = _canonical(before)
        elif fault == "final_main":
            before[wire.NAME]["settings"]["changed"] = "private"
            after = _canonical(before)
        elif fault == "final_count":
            final = replace(final, count=bootstrap.count + 1)
        else:
            final = replace(final, uuid="changedUuid")
    with pytest.raises(ValueError, match="^security_transition_mismatch$"):
        verify(original, current, bootstrap, final, after)
