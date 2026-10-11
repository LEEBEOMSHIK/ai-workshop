"""Synthetic response decoding; no native source authority or network access."""

import hashlib
import importlib
import json
from copy import deepcopy
from dataclasses import replace
from typing import Any
from uuid import UUID

import pytest

from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions

PROFILE = "11111111-1111-4111-8111-111111111111"
PROCESSING = "22222222-2222-4222-8222-222222222222"
BUILD = "33333333-3333-4333-8333-333333333333"
PROJECTION = "44444444-4444-4444-8444-444444444444"
ASSET = "55555555-5555-4555-8555-555555555555"
WORKSPACE = "66666666-6666-4666-8666-666666666666"
NAME = f"rag-{PROCESSING}-{PROFILE}-{BUILD}"
PERMISSIONS = AccessEpochPermissions("rag", ((UUID(PROFILE), UUID(PROCESSING)),))
LEGACY_NAME = f"rag-{PROFILE}-{BUILD}"
LEGACY_PERMISSIONS = AccessEpochPermissions("rag", ((UUID(PROFILE), None),))
PRIVATE = "synthetic-private-analysis-value"


@pytest.fixture
def api() -> Any:
    try:
        return importlib.import_module("ai_workshop.labs.rag.indexing.access_epoch_index_inventory")
    except ModuleNotFoundError:
        pytest.fail("strict private index inventory decoder is not implemented")


def raw(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True).encode()


def metadata() -> dict[str, Any]:
    return {
        NAME: {
            "aliases": {"rag-alias": {"filter": {"term": {"private": PRIVATE}}}},
            "settings": {
                "index.uuid": "syntheticIndexUUID12345",
                "index.creation_date": "1700000000000",
                "index.number_of_shards": "1",
                "index.number_of_replicas": "0",
                "index.version.created": "9050299",
                "index.analysis.filter.words.synonyms": [PRIVATE],
            },
            "defaults": {"index.refresh_interval": "1s", "private.setting": PRIVATE},
            "mappings": {
                "properties": {
                    "text": {"type": "text"},
                    "projection_id": {"type": "keyword"},
                    "index_build_id": {"type": "keyword"},
                    "indexing_profile_id": {"type": "keyword"},
                    "asset_version_id": {"type": "keyword"},
                    "workspace_id": {"type": "keyword"},
                    "rag_mapping_version": {"type": "integer"},
                },
                "_meta": {
                    "note": PRIVATE,
                    "rag": {
                        "mapping_version": 1,
                        "index_build_id": BUILD,
                        "projection_id": PROJECTION,
                        "indexing_profile_id": PROFILE,
                        "vector_dimension": 768,
                    },
                    "rag_index_resource": {
                        "contract_version": 1,
                        "resource_id": BUILD,
                        "job_id": "77777777-7777-4777-8777-777777777777",
                        "workspace_id": WORKSPACE,
                        "document_id": "88888888-8888-4888-8888-888888888888",
                        "asset_version_id": ASSET,
                        "document_processing_profile_id": PROCESSING,
                        "input_fingerprint": "a" * 64,
                        "chunk_ids_sha256": "b" * 64,
                    },
                },
            },
        }
    }


def legacy_metadata() -> dict[str, Any]:
    body = metadata()
    value = body.pop(NAME)
    del value["mappings"]["_meta"]["rag_index_resource"]
    for key in ("asset_version_id", "workspace_id"):
        del value["mappings"]["properties"][key]
    return {LEGACY_NAME: value}


def count(value: object = 3) -> dict[str, Any]:
    return {"count": value, "_shards": {"total": 1, "successful": 1, "skipped": 0, "failed": 0}}


def entry(api: Any, body: dict[str, Any] | None = None) -> Any:
    decoded = api.decode_index_metadata(NAME, PERMISSIONS, raw(body or metadata()))
    return api.decode_index_counts(decoded, raw(count()), raw(count()))


def listing() -> dict[str, Any]:
    return {
        "cluster_uuid": "syntheticClusterUUID123",
        "metadata": {
            "indices": {
                NAME: {"state": "open", "settings": {"index.uuid": "ragUuid"}},
                ".security-7": {
                    "state": "open",
                    "settings": {"index.uuid": "securityUuid", "index.hidden": "true"},
                },
                "foreign": {"state": "close", "settings": {"index.uuid": "foreignUuid"}},
            }
        },
    }


def test_listing_keeps_foreign_and_security_entries_visible(api: Any) -> None:
    result = api.decode_index_listing(raw(listing()))
    assert tuple(row.name for row in result.indices) == tuple(
        sorted((NAME, ".security-7", "foreign"))
    )
    assert result.indices[0].hidden is True
    assert result.indices[1].state == "close"
    assert result.cluster_uuid == "syntheticClusterUUID123"


@pytest.mark.parametrize(
    "bad",
    [
        b'{"metadata":{},"metadata":{}}',
        b'{"x":NaN}',
        b'{"x":1e999}',
        b"\xff",
        b"[]",
        b"{}",
        b" " * 262145,
        b'{"x":"\\ud800"}',
    ],
    ids=["duplicate", "nan", "infinity", "utf8", "array", "missing", "oversized", "surrogate"],
)
def test_bounded_strict_json_refuses_ambiguous_input(api: Any, bad: bytes) -> None:
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_listing(bad)


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_uuid",
        "boolean_hidden",
        "extra_entry_field",
        "missing_indices",
        "unsafe_name",
        "too_many",
    ],
)
def test_listing_refuses_incomplete_or_malformed_entries(api: Any, change: str) -> None:
    body = listing()
    rows = body["metadata"]["indices"]
    if change == "duplicate_uuid":
        rows["foreign"]["settings"]["index.uuid"] = "ragUuid"
    elif change == "boolean_hidden":
        rows[NAME]["settings"]["index.hidden"] = True
    elif change == "extra_entry_field":
        rows[NAME]["error"] = "private"
    elif change == "missing_indices":
        body["metadata"] = {}
    elif change == "unsafe_name":
        rows["other/_search"] = rows.pop("foreign")
    else:
        body["metadata"]["indices"] = {
            f"index-{n}": {"state": "open", "settings": {"index.uuid": f"uuid{n}"}}
            for n in range(1025)
        }
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_listing(raw(body))


def test_metadata_retains_complete_private_packet_and_emits_fixed_provenance_query(
    api: Any,
) -> None:
    body = metadata()
    decoded = api.decode_index_metadata(NAME, PERMISSIONS, raw(body))
    assert json.loads(decoded.private_metadata) == body
    query = api.provenance_count_body(decoded)
    assert json.loads(query.body) == {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"projection_id": PROJECTION}},
                    {"term": {"index_build_id": BUILD}},
                    {"term": {"indexing_profile_id": PROFILE}},
                    {"term": {"rag_mapping_version": 1}},
                    {"term": {"asset_version_id": ASSET}},
                    {"term": {"workspace_id": WORKSPACE}},
                ]
            }
        }
    }
    result = api.decode_index_counts(decoded, raw(count()), raw(count()))
    assert result.observation.name == NAME
    assert result.observation.uuid == "syntheticIndexUUID12345"
    assert result.observation.count == 3
    for value in (decoded, query, result):
        assert PRIVATE not in repr(value)
        assert "a" * 64 not in repr(value)
        assert WORKSPACE not in repr(value)


@pytest.mark.parametrize(
    "path,value",
    [
        (("settings", "index.number_of_shards"), True),
        (("settings", "index.number_of_shards"), "01"),
        (("settings", "index.number_of_replicas"), "-1"),
        (("settings", "index.creation_date"), 1700000000000),
        (("settings", "index.uuid"), "wrong/value"),
        (("settings", "index.version.created"), "0"),
        (("defaults", "index.refresh_interval"), "private-duration"),
        (("mappings", "_meta", "rag", "mapping_version"), True),
        (("mappings", "_meta", "rag", "mapping_version"), 2),
        (("mappings", "_meta", "rag", "vector_dimension"), 1.0),
        (("mappings", "_meta", "rag", "index_build_id"), PROFILE),
        (("mappings", "_meta", "rag", "indexing_profile_id"), BUILD),
        (("mappings", "_meta", "rag_index_resource", "resource_id"), PROFILE),
        (("mappings", "_meta", "rag_index_resource", "document_processing_profile_id"), BUILD),
        (("mappings", "_meta", "rag_index_resource", "contract_version"), True),
        (("mappings", "_meta", "rag_index_resource", "input_fingerprint"), "private-invalid"),
        (("mappings", "_meta"), "private-invalid"),
        (("aliases",), []),
    ],
)
def test_metadata_known_fields_require_exact_supported_types_and_binding(
    api: Any, path: tuple[str, ...], value: object
) -> None:
    body = metadata()
    target = body[NAME]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$") as caught:
        api.decode_index_metadata(NAME, PERMISSIONS, raw(body))
    assert "private" not in str(caught.value)


@pytest.mark.parametrize(
    "change",
    [
        "missing_tracked_for_processing",
        "missing_defaults",
        "foreign_namespace",
        "extra_index",
        "nested_duplicate",
        "deep",
        "huge_integer",
    ],
)
def test_metadata_does_not_guess_missing_or_ambiguous_provenance(api: Any, change: str) -> None:
    body = metadata()
    name = NAME
    if change == "missing_tracked_for_processing":
        del body[NAME]["mappings"]["_meta"]["rag_index_resource"]
    elif change == "missing_defaults":
        del body[NAME]["defaults"]
    elif change == "foreign_namespace":
        name = NAME.replace("rag-", "foreign-", 1)
        body[name] = body.pop(NAME)
    elif change == "extra_index":
        body["other"] = deepcopy(body[NAME])
    elif change == "deep":
        value: Any = {}
        for _ in range(40):
            value = {"next": value}
        body[NAME]["mappings"]["_meta"]["extra"] = value
    elif change == "huge_integer":
        body[NAME]["mappings"]["_meta"]["extra"] = 2**100
    payload = raw(body)
    if change == "nested_duplicate":
        payload = payload.replace(
            b'"mapping_version": 1', b'"mapping_version": 1, "mapping_version": 1'
        )
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(name, PERMISSIONS, payload)


@pytest.mark.parametrize(
    "path",
    [
        ("settings", "index.analysis.filter.words.synonyms"),
        ("defaults", "private.setting"),
        ("mappings", "_meta", "note"),
        ("mappings", "_meta", "rag_index_resource", "input_fingerprint"),
        ("mappings", "_meta", "rag_index_resource", "chunk_ids_sha256"),
        ("aliases", "rag-alias", "filter", "term", "private"),
    ],
)
def test_private_changes_leave_public_hashes_unchanged_but_fail_preservation(
    api: Any, path: tuple[str, ...]
) -> None:
    before = entry(api)
    body = metadata()
    target = body[NAME]
    for key in path[:-1]:
        target = target[key]
    previous = target[path[-1]]
    target[path[-1]] = ["changed"] if isinstance(previous, list) else "c" * 64
    after = entry(api, body)
    assert before.observation == after.observation
    with pytest.raises(ValueError, match="^index_inventory_preservation_mismatch$"):
        api.require_same_private_inventory((before,), (after,))


def test_canonical_order_is_stable_but_public_setting_change_is_visible(api: Any) -> None:
    before = entry(api)
    body = metadata()
    body[NAME]["settings"] = dict(reversed(tuple(body[NAME]["settings"].items())))
    after = entry(api, body)
    api.require_same_private_inventory((before,), (after,))
    body[NAME]["settings"]["index.number_of_replicas"] = "1"
    changed = entry(api, body)
    assert before.observation.settings_sha256 != changed.observation.settings_sha256
    assert before.observation.provenance_sha256 == changed.observation.provenance_sha256


@pytest.mark.parametrize(
    "field,value",
    [
        ("count", True),
        ("count", 3.0),
        ("count", -1),
        ("total", True),
        ("successful", 1.0),
        ("total", 0),
        ("failed", 1),
        ("skipped", 1),
        ("successful", 0),
    ],
)
def test_count_requires_complete_exact_integer_shard_results(
    api: Any, field: str, value: object
) -> None:
    decoded = api.decode_index_metadata(NAME, PERMISSIONS, raw(metadata()))
    body = count()
    if field == "count":
        body[field] = value
    else:
        body["_shards"][field] = value
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_counts(decoded, raw(body), raw(count()))


@pytest.mark.parametrize("change", ["mismatch", "error", "missing_shards", "partial", "early"])
def test_count_never_accepts_partial_or_mismatched_provenance(api: Any, change: str) -> None:
    decoded = api.decode_index_metadata(NAME, PERMISSIONS, raw(metadata()))
    body = count(2 if change == "mismatch" else 3)
    if change == "error":
        body["error"] = "synthetic-private-error"
    elif change == "missing_shards":
        del body["_shards"]
    elif change == "partial":
        body["_shards"]["failures"] = []
    elif change == "early":
        body["terminated_early"] = True
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_counts(decoded, raw(count()), raw(body))


def test_private_inventory_requires_same_unique_complete_name_set(api: Any) -> None:
    decoded = entry(api)
    api.require_same_private_inventory((), ())
    for before, after in (((decoded,), ()), ((decoded, decoded), (decoded, decoded))):
        with pytest.raises(ValueError, match="^index_inventory_preservation_mismatch$"):
            api.require_same_private_inventory(before, after)


@pytest.mark.parametrize("change", ["text", "normalizer", "runtime_shadow"])
def test_provenance_terms_cannot_use_analyzed_or_runtime_fields(api: Any, change: str) -> None:
    body = metadata()
    mappings = body[NAME]["mappings"]
    if change == "text":
        mappings["properties"]["projection_id"] = {"type": "text"}
    elif change == "normalizer":
        mappings["properties"]["projection_id"]["normalizer"] = "private_normalizer"
    else:
        mappings["runtime"] = {"projection_id": {"type": "keyword", "script": PRIVATE}}
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(NAME, PERMISSIONS, raw(body))


@pytest.mark.parametrize("section", ["defaults", "settings"])
def test_explicit_null_refresh_is_not_silently_omitted(api: Any, section: str) -> None:
    body = metadata()
    body[NAME][section]["index.refresh_interval"] = None
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(NAME, PERMISSIONS, raw(body))


def test_private_float_tokens_are_not_rounded_into_equal_packets(api: Any) -> None:
    source = raw(metadata())
    first = source.replace(b'"note":', b'"number": 0.10000000000000001, "note":')
    second = source.replace(b'"note":', b'"number": 0.1, "note":')
    decoded = [api.decode_index_metadata(NAME, PERMISSIONS, payload) for payload in (first, second)]
    entries = [api.decode_index_counts(item, raw(count()), raw(count())) for item in decoded]
    assert entries[0].observation == entries[1].observation
    assert b"0.10000000000000001" in decoded[0].private_metadata
    with pytest.raises(ValueError, match="^index_inventory_preservation_mismatch$"):
        api.require_same_private_inventory((entries[0],), (entries[1],))


def test_copied_metadata_cannot_inject_an_arbitrary_query(api: Any) -> None:
    decoded = api.decode_index_metadata(NAME, PERMISSIONS, raw(metadata()))
    forged = replace(decoded, _count_body=b'{"query":{"script":"synthetic"}}')
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.provenance_count_body(forged)


def test_unicode_canonical_packet_must_also_fit_the_private_bound(api: Any) -> None:
    body = metadata()
    body[NAME]["mappings"]["_meta"]["extra"] = ["\uac00" * 10000] * 8
    payload = json.dumps(body, ensure_ascii=False).encode()
    assert len(payload) < 256 * 1024
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(NAME, PERMISSIONS, payload)


def test_public_hash_preimages_contain_only_the_closed_nonsecret_fields(api: Any) -> None:
    result = entry(api).observation
    public_settings = {
        "contract": "public_index_settings_v1",
        "uuid": "syntheticIndexUUID12345",
        "creation_date": 1700000000000,
        "number_of_shards": 1,
        "number_of_replicas": 0,
        "version_created": 9050299,
        "refresh_interval_ms": 1000,
    }
    public_provenance = {
        "contract": "public_index_provenance_counts_v1",
        "schema": "tracked_v1",
        "mapping_version": 1,
        "index_build_id": BUILD,
        "projection_id": PROJECTION,
        "indexing_profile_id": PROFILE,
        "vector_dimension": 768,
        "resource_id": BUILD,
        "asset_version_id": ASSET,
        "document_processing_profile_id": PROCESSING,
        "total_count": 3,
        "provenance_count": 3,
    }
    for projection, actual in (
        (public_settings, result.settings_sha256),
        (public_provenance, result.provenance_sha256),
    ):
        expected = json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
        assert actual == hashlib.sha256(expected).hexdigest()


def test_refresh_is_normalized_but_private_representation_changes_still_fail(api: Any) -> None:
    before = entry(api)
    body = metadata()
    body[NAME]["defaults"]["index.refresh_interval"] = "1000ms"
    after = entry(api, body)
    assert before.observation == after.observation
    with pytest.raises(ValueError, match="^index_inventory_preservation_mismatch$"):
        api.require_same_private_inventory((before,), (after,))


def test_empty_inventory_decodes_without_claiming_complete_source_authority(api: Any) -> None:
    body = {"cluster_uuid": "clusterUuid", "metadata": {"indices": {}}}
    result = api.decode_index_listing(raw(body))
    assert result.indices == ()
    assert json.loads(result.private_listing) == body


@pytest.mark.parametrize("total_shards,provenance_shards", [(1, 1), (1, 2), (2, 1), (3, 3)])
def test_count_coverage_must_match_the_physical_index_shard_count(
    api: Any, total_shards: int, provenance_shards: int
) -> None:
    body = metadata()
    body[NAME]["settings"]["index.number_of_shards"] = "2"
    decoded = api.decode_index_metadata(NAME, PERMISSIONS, raw(body))
    total, provenance = count(), count()
    total["_shards"].update(total=total_shards, successful=total_shards)
    provenance["_shards"].update(total=provenance_shards, successful=provenance_shards)
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_counts(decoded, raw(total), raw(provenance))


def test_two_shard_index_accepts_two_complete_shard_count_responses(api: Any) -> None:
    body = metadata()
    body[NAME]["settings"]["index.number_of_shards"] = "2"
    decoded = api.decode_index_metadata(NAME, PERMISSIONS, raw(body))
    response = count()
    response["_shards"].update(total=2, successful=2)
    result = api.decode_index_counts(decoded, raw(response), raw(response))
    assert result.observation.count == 3
    assert result.observation.uuid == "syntheticIndexUUID12345"


def test_explicit_legacy_schema_uses_only_four_bound_provenance_terms(api: Any) -> None:
    body = legacy_metadata()
    decoded = api.decode_index_metadata(LEGACY_NAME, LEGACY_PERMISSIONS, raw(body))
    assert decoded.schema == "legacy_rag_v1"
    assert json.loads(decoded.private_metadata) == body
    assert json.loads(api.provenance_count_body(decoded).body) == {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"projection_id": PROJECTION}},
                    {"term": {"index_build_id": BUILD}},
                    {"term": {"indexing_profile_id": PROFILE}},
                    {"term": {"rag_mapping_version": 1}},
                ]
            }
        }
    }
    result = api.decode_index_counts(decoded, raw(count()), raw(count()))
    public = {
        "contract": "public_index_provenance_counts_v1",
        "schema": "legacy_rag_v1",
        "mapping_version": 1,
        "index_build_id": BUILD,
        "projection_id": PROJECTION,
        "indexing_profile_id": PROFILE,
        "vector_dimension": 768,
        "total_count": 3,
        "provenance_count": 3,
    }
    expected = json.dumps(public, sort_keys=True, separators=(",", ":")).encode()
    assert result.observation.provenance_sha256 == hashlib.sha256(expected).hexdigest()
    assert result.observation.provenance_sha256 != entry(api).observation.provenance_sha256


@pytest.mark.parametrize("value", [None, {}, [], "synthetic-private-invalid", False])
def test_present_invalid_tracked_metadata_never_falls_back_to_legacy(
    api: Any, value: object
) -> None:
    body = legacy_metadata()
    body[LEGACY_NAME]["mappings"]["_meta"]["rag_index_resource"] = value
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(LEGACY_NAME, LEGACY_PERMISSIONS, raw(body))


@pytest.mark.parametrize("change", ["no_rag", "profile", "build", "version", "analyzed", "runtime"])
def test_legacy_requires_the_known_bound_rag_schema(api: Any, change: str) -> None:
    body = legacy_metadata()
    mappings = body[LEGACY_NAME]["mappings"]
    if change == "no_rag":
        del mappings["_meta"]["rag"]
    elif change == "profile":
        mappings["_meta"]["rag"]["indexing_profile_id"] = BUILD
    elif change == "build":
        mappings["_meta"]["rag"]["index_build_id"] = PROFILE
    elif change == "version":
        mappings["_meta"]["rag"]["mapping_version"] = True
    elif change == "analyzed":
        mappings["properties"]["projection_id"] = {"type": "text"}
    else:
        mappings["runtime"] = {"projection_id": {"type": "keyword"}}
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(LEGACY_NAME, LEGACY_PERMISSIONS, raw(body))


@pytest.mark.parametrize("change", ["private_note", "analysis", "alias_filter"])
def test_legacy_private_changes_still_fail_whole_private_comparison(api: Any, change: str) -> None:
    body = legacy_metadata()
    first = api.decode_index_metadata(LEGACY_NAME, LEGACY_PERMISSIONS, raw(body))
    value = body[LEGACY_NAME]
    if change == "private_note":
        value["mappings"]["_meta"]["note"] = "changed-synthetic-private"
    elif change == "analysis":
        value["settings"]["index.analysis.filter.words.synonyms"] = ["changed"]
    else:
        value["aliases"]["rag-alias"]["filter"] = {"term": {"private": "changed"}}
    second = api.decode_index_metadata(LEGACY_NAME, LEGACY_PERMISSIONS, raw(body))
    before = api.decode_index_counts(first, raw(count()), raw(count()))
    after = api.decode_index_counts(second, raw(count()), raw(count()))
    assert before.observation == after.observation
    with pytest.raises(ValueError, match="^index_inventory_preservation_mismatch$"):
        api.require_same_private_inventory((before,), (after,))


def test_legacy_count_is_bound_to_the_metadata_shard_count(api: Any) -> None:
    body = legacy_metadata()
    body[LEGACY_NAME]["settings"]["index.number_of_shards"] = "2"
    decoded = api.decode_index_metadata(LEGACY_NAME, LEGACY_PERMISSIONS, raw(body))
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_counts(decoded, raw(count()), raw(count()))
    response = count()
    response["_shards"].update(total=2, successful=2)
    assert api.decode_index_counts(decoded, raw(response), raw(response)).observation.count == 3


def test_legacy_cannot_use_a_processing_namespace_or_foreign_prefix(api: Any) -> None:
    body = legacy_metadata()
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(LEGACY_NAME, PERMISSIONS, raw(body))
    foreign = LEGACY_NAME.replace("rag-", "foreign-", 1)
    with pytest.raises(ValueError, match="^index_inventory_decode_denied$"):
        api.decode_index_metadata(foreign, LEGACY_PERMISSIONS, raw({foreign: body[LEGACY_NAME]}))
