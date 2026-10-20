"""Lossless HTTP-only factoring; source evidence and citation IDs remain unchanged."""

from collections import defaultdict

_SHARED_FIELDS = ("group_id", "page", "source_kind", "source_part", "table_cell", "section_path")

GROUP_NOTICE = (
    "Each evidence group_ref is a zero-based index into evidence_groups. "
    "Merge that group's fields with the evidence item to recover its source metadata. "
    "Only exact evidence_id UUIDs are citations; group_ref and group_id are not citations. "
    "Shared metadata does not imply that items describe the same subject."
)


def group_http_evidence(
    evidence: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    members: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in evidence:
        members[str(item["group_id"])].append(item)
    references = {identity: index for index, identity in enumerate(members)}
    groups = [{
        key: items[0][key] for key in _SHARED_FIELDS
        if all(item[key] == items[0][key] for item in items)
    } for items in members.values()]
    items = []
    for item in evidence:
        reference = references[str(item["group_id"])]
        items.append({
            "group_ref": reference,
            **{key: value for key, value in item.items() if key not in groups[reference]},
        })
    return items, groups
