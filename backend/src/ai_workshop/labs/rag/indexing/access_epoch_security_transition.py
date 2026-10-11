"""Pure exhaustive private-map comparison, never native creation authority.

The composing issuer must validate actual descriptor/capture origins and each
category's counts. No reduced foreign DTO or security-prefix exemption is used.
"""

from typing import Any

from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    _canonical,
    _identifier,
    _integer,
    _load,
    _name,
    _object,
)
from ai_workshop.labs.rag.indexing.access_epoch_security_inventory import DecodedMainSecurityIndex

_MISMATCH = "security_transition_mismatch"
_MAIN = ".security-7"
_ALIAS = ".security"


def _indices(raw: bytes) -> dict[str, Any]:
    indices = _object(_object(_load(raw)["metadata"])["indices"])
    if len(indices) > 1024:
        raise ValueError(_MISMATCH)
    uuids: set[str] = set()
    for name, value in indices.items():
        _name(name)
        row = _object(value)
        if set(row) != {"state", "system", "aliases", "settings", "mappings"} or (
            row["state"] != "open" or type(row["system"]) is not bool
        ):
            raise ValueError(_MISMATCH)
        _object(row["mappings"])
        settings = _object(row["settings"])
        uuid = _identifier(settings["index.uuid"])
        if uuid in uuids:
            raise ValueError(_MISMATCH)
        uuids.add(uuid)
        if settings.get("index.hidden", "false") not in {"true", "false"}:
            raise ValueError(_MISMATCH)
        aliases = row["aliases"]
        if type(aliases) is list:
            names = [_name(alias) for alias in aliases]
            if len(set(names)) != len(names):
                raise ValueError(_MISMATCH)
        else:
            for alias in _object(aliases):
                _name(alias)
    return indices


def _main(indices: dict[str, Any], decoded: DecodedMainSecurityIndex) -> None:
    if type(decoded) is not DecodedMainSecurityIndex or (
        type(decoded.name) is not str
        or decoded.name != _MAIN
        or type(decoded.schema) is not str
        or decoded.schema != "main_security_es_9_5_2_v1"
        or type(decoded.count_kind) is not str
        or decoded.count_kind != "lucene_live_docs"
    ):
        raise ValueError(_MISMATCH)
    _integer(decoded.count)
    _identifier(decoded.uuid)
    row = _object(indices[_MAIN])
    physical = {name: value["settings"]["index.uuid"] for name, value in indices.items()}
    if (
        row["system"] is not True
        or row["aliases"] != [_ALIAS]
        or row["settings"].get("index.hidden") != "true"
        or row["settings"]["index.uuid"] != decoded.uuid
        or _canonical({_MAIN: row}) != decoded.private_metadata
        or _canonical(physical) != decoded.private_physical_inventory
        or {name for name, value in indices.items() if value["system"]} != {_MAIN}
        or {name for name, value in indices.items() if _ALIAS in value["aliases"]} != {_MAIN}
    ):
        raise ValueError(_MISMATCH)


def require_main_security_transition(
    original_state: bytes,
    bootstrap_state: bytes,
    bootstrap: DecodedMainSecurityIndex,
    *,
    final_state: bytes | None = None,
    final: DecodedMainSecurityIndex | None = None,
) -> None:
    """Require full B=O union S and optional F=B, without issuing evidence."""
    try:
        if (final_state is None) != (final is None):
            raise ValueError(_MISMATCH)
        original, current = _indices(original_state), _indices(bootstrap_state)
        if (
            _MAIN in original
            or any(row["system"] or _ALIAS in row["aliases"] for row in original.values())
            or set(current) != set(original) | {_MAIN}
        ):
            raise ValueError(_MISMATCH)
        _main(current, bootstrap)
        for name, row in original.items():
            if _canonical(row) != _canonical(current[name]):
                raise ValueError(_MISMATCH)
        if final_state is not None and final is not None:
            after = _indices(final_state)
            _main(after, final)
            if (
                _canonical(current) != _canonical(after)
                or bootstrap.uuid != final.uuid
                or bootstrap.count != final.count
            ):
                raise ValueError(_MISMATCH)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise ValueError(_MISMATCH) from None
