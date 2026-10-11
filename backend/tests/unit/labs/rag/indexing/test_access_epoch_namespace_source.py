"""Source-issued existing namespaces; HTTP, SQL and native reads remain synthetic."""

import asyncio
import gzip
import importlib
import json
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

MODULE = "ai_workshop.labs.rag.indexing.access_epoch_namespace_source"


def test_namespace_module_exists() -> None:
    assert importlib.util.find_spec(MODULE) is not None


@pytest.fixture
async def case(monkeypatch: Any, tmp_path: Path) -> Any:
    source = importlib.import_module(MODULE)
    fixture = importlib.import_module("tests.unit.labs.rag.indexing.test_access_epoch_native")
    wire = importlib.import_module("tests.unit.labs.rag.indexing.test_access_epoch_index_inventory")
    original, snapshot, _runner, _reader = fixture.deployment_case(monkeypatch)
    settings = original.settings
    settings.elasticsearch_index_prefix = "rag"
    settings.database_url = (
        "postgresql+psycopg://synthetic:synthetic@127.0.0.1:15432/ai_workshop_local_clean"
    )
    snapshot = replace(
        snapshot,
        indexing_profile_id=UUID(wire.PROFILE),
        document_processing_profile_id=UUID(wire.PROCESSING),
        alias=f"rag-{wire.PROCESSING}-{wire.PROFILE}-active",
        targets=(wire.NAME,),
    )
    observed = await original.observe_deployment(snapshot)
    body = wire.metadata()[wire.NAME]
    body["aliases"] = [snapshot.alias]
    body.pop("defaults")
    body["mappings"] = {"_doc": body["mappings"]}
    body.update(state="open", system=False)
    metadata = {"cluster_uuid": snapshot.cluster_uuid, "metadata": {"indices": {wire.NAME: body}}}
    listing = {
        "cluster_uuid": snapshot.cluster_uuid,
        "metadata": {
            "indices": {
                wire.NAME: {
                    "state": "open",
                    "settings": {"index.uuid": body["settings"]["index.uuid"]},
                },
            }
        },
    }
    value = SimpleNamespace(
        source=source,
        original=original,
        snapshot=snapshot,
        observed=observed,
        settings=settings,
        metadata=metadata,
        listing=listing,
        wire=wire,
        calls=[],
        accept_encodings=[],
        db_calls=0,
        disposed=0,
        fault=None,
        profiles=[(UUID(wire.PROFILE), "indexing"), (UUID(wire.PROCESSING), "document_processing")],
        profile_passes=None,
        db_fault=None,
        db_requested=[],
    )
    monkeypatch.setattr(source, "PROJECT_ROOT", tmp_path)
    (tmp_path / ".env").write_text("# synthetic source\n", encoding="utf-8")
    monkeypatch.setattr(source, "Settings", lambda **_kw: settings)
    client_class = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        value.calls.append(str(request.url))
        value.accept_encodings.append(request.headers.get("accept-encoding"))
        assert request.method == "GET" and request.url.host == "127.0.0.1"
        assert request.url.port == 9200 and "authorization" not in request.headers
        if value.fault == "redirect":
            return httpx.Response(302, headers={"Location": "http://outside.invalid"})
        if value.fault == "oversize":
            return httpx.Response(200, content=b"x" * 262145)
        if value.fault == "duplicate_json":
            return httpx.Response(200, content=b'{"metadata":{},"metadata":{}}')
        if value.fault == "private_error":
            raise RuntimeError("synthetic-private-error-body")
        if value.fault == "cancel":
            raise asyncio.CancelledError
        body = value.listing if request.url.path.endswith("/metadata") else value.metadata
        if value.fault == "forced_gzip" or (
            value.fault == "negotiate_encoding"
            and request.headers.get("accept-encoding") != "identity"
        ):
            return httpx.Response(
                200,
                content=gzip.compress(json.dumps(body).encode()),
                headers={"Content-Encoding": "gzip"},
            )
        return httpx.Response(200, content=json.dumps(body).encode())

    def client(**kwargs: Any) -> httpx.AsyncClient:
        assert kwargs["trust_env"] is False and kwargs["follow_redirects"] is False
        assert 0 < kwargs["timeout"] <= 10
        return client_class(transport=httpx.MockTransport(handler), **kwargs)

    class Connection:
        async def execute(self, statement: Any) -> Any:
            value.db_calls += 1
            assert str(statement).startswith("SELECT ")
            value.db_requested.append(tuple(next(iter(statement.compile().params.values()))))
            if value.db_fault:
                raise RuntimeError("synthetic-private-sql-error")
            rows = (
                value.profiles
                if value.profile_passes is None
                else value.profile_passes[value.db_calls - 1]
            )
            return SimpleNamespace(all=lambda: rows)

    class Engine:
        @asynccontextmanager
        async def connect(self) -> Any:
            yield Connection()

        async def dispose(self) -> None:
            value.disposed += 1

    monkeypatch.setattr(source.httpx, "AsyncClient", client)
    monkeypatch.setattr(source, "create_engine", lambda actual: Engine())
    value.issuer = source.OriginalNamespaceSource(settings, original, observed)
    return value


async def test_exact_existing_namespace_issued_from_original_sources(case: Any) -> None:
    cap = await case.issuer.observe(case.snapshot)
    assert cap.permissions.namespaces == ((UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),)
    assert cap.permissions.aliases == (case.snapshot.alias,)
    assert cap.snapshot_sha256 == case.snapshot.sha256
    assert cap.original_deployment_sha256 == case.observed.identity.deployment_sha256
    assert case.issuer.assert_issued(cap) is None
    assert len(case.calls) == 4 and case.db_calls == 2 and case.disposed == 2
    assert "synthetic-private" not in repr(cap)
    with pytest.raises(ValueError):
        case.issuer.assert_issued(replace(cap))


@pytest.mark.parametrize(
    "mode",
    [
        "unknown_profile",
        "wrong_kind",
        "duplicate_profile",
        "lookalike",
        "mapping_profile",
        "processing",
        "null_resource",
        "foreign_only",
        "system_rag",
        "missing_index",
        "uuid_mismatch",
        "snapshot_alias",
    ],
)
async def test_no_silent_widening_or_unknown_namespace(case: Any, mode: str) -> None:
    row = case.metadata["metadata"]["indices"][case.wire.NAME]
    meta = row["mappings"]["_doc"]["_meta"]
    if mode == "unknown_profile":
        case.profiles.pop()
    elif mode == "wrong_kind":
        case.profiles[0] = (UUID(case.wire.PROFILE), "generation")
    elif mode == "duplicate_profile":
        case.profiles.append(case.profiles[0])
    elif mode == "lookalike":
        del row["mappings"]["_doc"]["_meta"]
    elif mode == "mapping_profile":
        meta["rag"]["indexing_profile_id"] = str(uuid4())
    elif mode == "processing":
        meta["rag_index_resource"]["document_processing_profile_id"] = str(uuid4())
    elif mode == "null_resource":
        meta["rag_index_resource"] = None
    elif mode == "foreign_only":
        case.metadata["metadata"]["indices"] = {}
        case.listing["metadata"]["indices"] = {}
    elif mode == "system_rag":
        row["system"] = True
    elif mode == "missing_index":
        case.listing["metadata"]["indices"] = {}
    elif mode == "uuid_mismatch":
        row["settings"]["index.uuid"] = "differentUuid"
    else:
        case.snapshot = replace(case.snapshot, alias="rag-foreign-active")
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)


@pytest.mark.parametrize("mode", ["redirect", "oversize", "duplicate_json", "private_error"])
async def test_http_does_not_follow_or_accept_unbounded_responses(case: Any, mode: str) -> None:
    case.fault = mode
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)
    assert len(case.calls) <= 2 and case.db_calls == 0


async def test_other_db_profiles_never_form_cartesian_namespaces(case: Any) -> None:
    # A scope query must reject unrelated rows rather than grant a DB-wide product.
    case.profiles.append((uuid4(), "indexing"))
    with pytest.raises(ValueError):
        await case.issuer.observe(case.snapshot)


@pytest.mark.parametrize("mode", ["copied_observation", "copied_settings", "different_observer"])
async def test_constructor_requires_same_original_issuer(case: Any, mode: str) -> None:
    original, observation, settings = case.original, case.observed, case.settings
    if mode == "copied_observation":
        observation = replace(observation)
    elif mode == "copied_settings":
        settings = settings.model_copy()
    else:
        original = type(original)(settings)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        case.source.OriginalNamespaceSource(settings, original, observation)


@pytest.mark.parametrize("mode", ["prefix", "profile_uuid", "namespace_list", "nonce"])
async def test_nested_capability_mutation_rejected(case: Any, mode: str) -> None:
    cap = await case.issuer.observe(case.snapshot)
    if mode == "prefix":
        object.__setattr__(cap.permissions, "prefix", "outside")
    elif mode == "profile_uuid":
        object.__setattr__(cap.permissions.namespaces[0][0], "int", uuid4().int)
    elif mode == "namespace_list":
        object.__setattr__(cap.permissions, "namespaces", list(cap.permissions.namespaces))
    else:
        object.__setattr__(cap, "nonce", uuid4())
    with pytest.raises(ValueError):
        case.issuer.assert_issued(cap)


async def test_original_identity_change_never_issues(case: Any, monkeypatch: Any) -> None:
    async def changed(_snapshot: object) -> Any:
        return replace(case.observed.identity, ephemeral_id="changed")

    monkeypatch.setattr(case.original, "observe_original", changed)
    with pytest.raises(ValueError):
        await case.issuer.observe(case.snapshot)
    assert case.calls == []


async def test_retained_source_cannot_swap_to_another_valid_observation(case: Any) -> None:
    cap = await case.issuer.observe(case.snapshot)
    case.issuer.observation = await case.original.observe_deployment(case.snapshot)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        case.issuer.assert_issued(cap)


@pytest.mark.parametrize(
    "field,value",
    [("elasticsearch_access_epoch", 1), ("elasticsearch_ca_certs", Path("synthetic.pem"))],
)
async def test_mutated_partial_secured_context_is_denied(
    case: Any, field: str, value: object
) -> None:
    setattr(case.settings, field, value)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)


async def test_observed_tracked_and_legacy_pairs_only(case: Any) -> None:
    wire = case.wire
    row = wire.legacy_metadata()[wire.LEGACY_NAME]
    row.pop("defaults")
    row["aliases"] = []
    row["settings"]["index.uuid"] = "syntheticLegacyUUID123"
    row["mappings"] = {"_doc": row["mappings"]}
    row.update(state="open", system=False)
    case.metadata["metadata"]["indices"][wire.LEGACY_NAME] = row
    case.listing["metadata"]["indices"][wire.LEGACY_NAME] = {
        "state": "open",
        "settings": {"index.uuid": "syntheticLegacyUUID123"},
    }
    case.profiles.append((case.source.LEGACY_DOCUMENT_PROCESSING_PROFILE_ID, "document_processing"))
    cap = await case.issuer.observe(case.snapshot)
    assert set(cap.permissions.namespaces) == {
        (UUID(wire.PROFILE), None),
        (UUID(wire.PROFILE), UUID(wire.PROCESSING)),
    }


@pytest.mark.parametrize("change", ["metadata", "listing", "db", "identity"])
async def test_bracket_changes_never_issue(case: Any, monkeypatch: Any, change: str) -> None:
    read = case.issuer._read
    calls = 0

    async def changing(path: str) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 3:
            if change == "metadata":
                case.metadata["metadata"]["indices"][case.wire.NAME]["mappings"]["_doc"]["_meta"][
                    "note"
                ] = "changed synthetic private"
            elif change == "listing":
                case.listing["metadata"]["indices"][case.wire.NAME]["settings"]["index.uuid"] = (
                    "changedUuid"
                )
            elif change == "db":
                case.profiles[0] = (UUID(case.wire.PROFILE), "generation")
            else:

                async def changed(_snapshot: object) -> Any:
                    return replace(case.observed.identity, ephemeral_id="changed")

                monkeypatch.setattr(case.original, "observe_original", changed)
        result: bytes = await read(path)
        return result

    monkeypatch.setattr(case.issuer, "_read", changing)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)


async def test_foreign_indices_remain_complete_but_never_granted(case: Any) -> None:
    row = {
        "state": "open",
        "system": False,
        "settings": {"index.uuid": "foreignUUID123"},
        "mappings": {"_doc": {"properties": {"message": {"type": "text"}}}},
        "aliases": [],
    }
    case.metadata["metadata"]["indices"]["foreign-data"] = row
    case.listing["metadata"]["indices"]["foreign-data"] = {
        "state": "open",
        "settings": deepcopy(row["settings"]),
    }
    cap = await case.issuer.observe(case.snapshot)
    assert cap.permissions.namespaces == ((UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),)
    row["aliases"] = [case.snapshot.alias]
    with pytest.raises(ValueError):
        await case.issuer.observe(case.snapshot)


async def test_cancellation_propagates_without_issued_capability(case: Any) -> None:
    case.fault = "cancel"
    with pytest.raises(asyncio.CancelledError):
        await case.issuer.observe(case.snapshot)
    assert not case.issuer._issued


async def test_environment_drift_denies_even_previously_issued_capability(
    case: Any, monkeypatch: Any
) -> None:
    cap = await case.issuer.observe(case.snapshot)
    changed = case.settings.model_copy(update={"elasticsearch_index_prefix": "outside"})
    monkeypatch.setattr(case.source, "Settings", lambda **_kw: changed)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        case.issuer.assert_issued(cap)


async def test_foreign_issuer_cannot_adopt_other_sources_capability(case: Any) -> None:
    cap = await case.issuer.observe(case.snapshot)
    other = case.source.OriginalNamespaceSource(case.settings, case.original, case.observed)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        other.assert_issued(cap)


async def test_source_explicitly_requests_identity_encoding_on_every_get(case: Any) -> None:
    case.fault = "negotiate_encoding"
    cap = await case.issuer.observe(case.snapshot)
    case.issuer.assert_issued(cap)
    assert case.accept_encodings == ["identity"] * 4


async def test_server_ignoring_identity_encoding_is_still_denied(case: Any) -> None:
    case.fault = "forced_gzip"
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)
    assert case.db_calls == 0 and not case.issuer._issued


@pytest.mark.parametrize("alias", ["outside-noncanonical-active", "current_collision"])
async def test_outside_legacy_is_preserved_without_permission_or_profile_grant(
    case: Any, alias: str
) -> None:
    name = case.wire.LEGACY_NAME.replace("rag-", "outside-", 1)
    row = case.wire.legacy_metadata()[case.wire.LEGACY_NAME]
    row.pop("defaults")
    row["settings"]["index.uuid"] = "syntheticOutsideLegacyUUID123"
    row["aliases"] = [case.snapshot.alias if alias == "current_collision" else alias]
    row["mappings"] = {"_doc": row["mappings"]}
    row.update(state="open", system=False)
    case.metadata["metadata"]["indices"][name] = row
    case.listing["metadata"]["indices"][name] = {
        "state": "open",
        "settings": {"index.uuid": row["settings"]["index.uuid"]},
    }
    if alias == "current_collision":
        with pytest.raises(ValueError, match="^original_namespace_unverified$"):
            await case.issuer.observe(case.snapshot)
    else:
        cap = await case.issuer.observe(case.snapshot)
        assert cap.permissions.namespaces == (
            (UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),
        )
        assert cap.permissions.aliases == (case.snapshot.alias,)
        assert case.db_calls == 2


async def test_outside_private_metadata_change_still_denies_complete_source(
    case: Any, monkeypatch: Any
) -> None:
    name = "outside-data"
    row: dict[str, Any] = {
        "state": "open",
        "system": False,
        "settings": {"index.uuid": "outsideUUID123"},
        "mappings": {"_doc": {"_meta": {"private": "synthetic-first"}}},
        "aliases": ["outside-noncanonical-active"],
    }
    case.metadata["metadata"]["indices"][name] = row
    case.listing["metadata"]["indices"][name] = {
        "state": "open",
        "settings": deepcopy(row["settings"]),
    }
    read = case.issuer._read
    calls = 0

    async def changing(path: str) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 3:
            row["mappings"]["_doc"]["_meta"]["private"] = "synthetic-changed"
        result: bytes = await read(path)
        return result

    monkeypatch.setattr(case.issuer, "_read", changing)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)


def add_legacy(
    case: Any, profile: UUID, *, prefix: str = "rag", aliases: tuple[str, ...] = ()
) -> str:
    build = uuid4()
    name = f"{prefix}-{profile}-{build}"
    row = case.wire.legacy_metadata()[case.wire.LEGACY_NAME]
    row.pop("defaults")
    row["aliases"] = list(aliases)
    row["settings"]["index.uuid"] = "syntheticLegacy" + build.hex
    row["mappings"]["_meta"]["rag"].update(
        indexing_profile_id=str(profile), index_build_id=str(build)
    )
    row["mappings"] = {"_doc": row["mappings"]}
    row.update(state="open", system=False)
    case.metadata["metadata"]["indices"][name] = row
    case.listing["metadata"]["indices"][name] = {
        "state": "open",
        "settings": {"index.uuid": row["settings"]["index.uuid"]},
    }
    return name


async def test_known_legacy_missing_profile_is_retained_without_namespace_grant(case: Any) -> None:
    orphan = uuid4()
    name = add_legacy(case, orphan)
    case.profiles.append((case.source.LEGACY_DOCUMENT_PROCESSING_PROFILE_ID, "document_processing"))
    cap = await case.issuer.observe(case.snapshot)
    unmanaged = case.issuer.unmanaged(cap)
    assert cap.permissions.namespaces == ((UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),)
    assert len(unmanaged.entries) == 1
    entry = unmanaged.entries[0]
    assert (entry.name, entry.indexing_profile_id, entry.reason) == (
        name,
        orphan,
        "missing_indexing_profile",
    )
    assert unmanaged.namespace_nonce == cap.nonce
    assert unmanaged.snapshot_sha256 == cap.snapshot_sha256
    assert unmanaged.original_deployment_sha256 == cap.original_deployment_sha256
    assert json.loads(entry.private_metadata) == {name: case.metadata["metadata"]["indices"][name]}
    assert case.issuer.assert_issued(cap) is None
    assert case.issuer.assert_unmanaged_issued(unmanaged) is None
    assert case.db_calls == 2 and all(orphan in requested for requested in case.db_requested)
    assert all("_cluster/state/" in path for path in case.calls)
    with pytest.raises(ValueError):
        cap.permissions.authorize("collector", "get", (name,))
    assert "synthetic-private" not in repr(unmanaged)


async def test_mixed_outside_and_orphan_exclusions_are_complete_and_source_owned(case: Any) -> None:
    orphan = uuid4()
    names = [add_legacy(case, orphan)]
    names += [
        add_legacy(case, uuid4(), prefix=prefix, aliases=(prefix + "-noncanonical",))
        for prefix in ("outside", "different")
    ]
    case.profiles.append((case.source.LEGACY_DOCUMENT_PROCESSING_PROFILE_ID, "document_processing"))
    cap = await case.issuer.observe(case.snapshot)
    unmanaged = case.issuer.unmanaged(cap)
    assert {entry.name for entry in unmanaged.entries} == set(names)
    assert [entry.reason for entry in unmanaged.entries].count("missing_indexing_profile") == 1
    assert [entry.reason for entry in unmanaged.entries].count("outside_configured_prefix") == 2
    assert cap.permissions.namespaces == ((UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),)
    for name in names:
        with pytest.raises(ValueError):
            cap.permissions.authorize("writer", "get", (name,))


@pytest.mark.parametrize(
    "mutation",
    [
        "copied",
        "entry_uuid",
        "profile_uuid",
        "entry_metadata",
        "entry_reason",
        "entry_aliases",
        "namespace_nonce",
        "snapshot",
        "entry_tuple",
        "foreign_issuer",
        "parent_permissions",
    ],
)
async def test_unmanaged_evidence_mutation_revokes_parent_and_companion(
    case: Any, mutation: str
) -> None:
    add_legacy(case, uuid4())
    case.profiles.append((case.source.LEGACY_DOCUMENT_PROCESSING_PROFILE_ID, "document_processing"))
    cap = await case.issuer.observe(case.snapshot)
    unmanaged = case.issuer.unmanaged(cap)
    if mutation == "copied":
        with pytest.raises(ValueError):
            case.issuer.assert_unmanaged_issued(replace(unmanaged))
        return
    if mutation == "foreign_issuer":
        other = case.source.OriginalNamespaceSource(case.settings, case.original, case.observed)
        with pytest.raises(ValueError):
            other.unmanaged(cap)
        with pytest.raises(ValueError):
            other.assert_unmanaged_issued(unmanaged)
        return
    if mutation == "parent_permissions":
        object.__setattr__(cap.permissions, "prefix", "foreign")
    elif mutation == "entry_uuid":
        object.__setattr__(unmanaged.entries[0], "uuid", "replacedUuid")
    elif mutation == "profile_uuid":
        object.__setattr__(unmanaged.entries[0].indexing_profile_id, "int", uuid4().int)
    elif mutation == "entry_metadata":
        object.__setattr__(unmanaged.entries[0], "private_metadata", b"{}")
    elif mutation == "entry_reason":
        object.__setattr__(unmanaged.entries[0], "reason", "unknown")
    elif mutation == "entry_aliases":
        object.__setattr__(unmanaged.entries[0], "aliases", ("replaced",))
    elif mutation == "namespace_nonce":
        object.__setattr__(unmanaged, "namespace_nonce", uuid4())
    elif mutation == "snapshot":
        object.__setattr__(unmanaged, "snapshot_sha256", "a" * 64)
    else:
        object.__setattr__(unmanaged, "entries", list(unmanaged.entries))
    with pytest.raises(ValueError):
        case.issuer.assert_issued(cap)
    with pytest.raises(ValueError):
        case.issuer.assert_unmanaged_issued(unmanaged)


@pytest.mark.parametrize(
    "fault",
    [
        "snapshot_profile",
        "snapshot_target",
        "processing_missing",
        "wrong_kind",
        "duplicate",
        "sql_error",
        "missing_one_pass",
        "two_missing",
        "alias_collision",
        "malformed_resource",
        "malformed_legacy",
        "tracked_missing",
    ],
)
async def test_only_completed_supported_legacy_absence_can_be_excluded(
    case: Any, fault: str
) -> None:
    orphan = uuid4()
    name = add_legacy(case, orphan)
    processing = case.source.LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
    case.profiles.append((processing, "document_processing"))
    row = case.metadata["metadata"]["indices"][name]
    if fault == "snapshot_profile":
        case.profiles.pop(0)
    elif fault == "snapshot_target":
        case.snapshot = replace(case.snapshot, targets=(case.wire.NAME, name))
    elif fault == "processing_missing":
        case.profiles.pop()
    elif fault == "wrong_kind":
        case.profiles.append((orphan, "generation"))
    elif fault == "duplicate":
        case.profiles += [(orphan, "indexing"), (orphan, "indexing")]
    elif fault == "sql_error":
        case.db_fault = True
    elif fault == "missing_one_pass":
        case.profile_passes = [list(case.profiles), [*case.profiles, (orphan, "indexing")]]
    elif fault == "two_missing":
        add_legacy(case, uuid4())
    elif fault == "alias_collision":
        row["aliases"] = [case.snapshot.alias]
    elif fault == "malformed_resource":
        row["mappings"]["_doc"]["_meta"]["rag_index_resource"] = None
    elif fault == "malformed_legacy":
        row["mappings"]["_doc"]["_meta"]["rag"]["mapping_version"] = True
    else:
        case.profiles.pop(0)
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)
    assert not case.issuer._issued


async def test_same_missing_profile_multiple_builds_is_one_bounded_absence(case: Any) -> None:
    orphan = uuid4()
    names = {add_legacy(case, orphan), add_legacy(case, orphan)}
    case.profiles.append((case.source.LEGACY_DOCUMENT_PROCESSING_PROFILE_ID, "document_processing"))
    cap = await case.issuer.observe(case.snapshot)
    assert {entry.name for entry in case.issuer.unmanaged(cap).entries} == names
    assert {entry.indexing_profile_id for entry in case.issuer.unmanaged(cap).entries} == {orphan}
    assert cap.permissions.namespaces == ((UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),)
    assert len(case.db_requested) == 2 and set(case.db_requested[0]) == set(case.db_requested[1])


@pytest.mark.parametrize(
    "fault",
    [
        "tracked",
        "rag_missing",
        "wrong_build",
        "unsupported_version",
        "hidden",
        "system",
        "name_profile",
        "malformed_properties",
    ],
)
async def test_outside_rag_requires_complete_explicit_legacy_schema(case: Any, fault: str) -> None:
    name = add_legacy(case, uuid4(), prefix="outside")
    row = case.metadata["metadata"]["indices"][name]
    mapping = row["mappings"]["_doc"]
    if fault == "tracked":
        mapping["_meta"]["rag_index_resource"] = None
    elif fault == "rag_missing":
        del mapping["_meta"]["rag"]
    elif fault == "wrong_build":
        mapping["_meta"]["rag"]["index_build_id"] = str(uuid4())
    elif fault == "unsupported_version":
        mapping["_meta"]["rag"]["mapping_version"] = 2
    elif fault == "hidden":
        row["settings"]["index.hidden"] = "true"
        case.listing["metadata"]["indices"][name]["settings"]["index.hidden"] = "true"
    elif fault == "system":
        row["system"] = True
    elif fault == "name_profile":
        changed = name.replace(str(mapping["_meta"]["rag"]["indexing_profile_id"]), str(uuid4()))
        case.metadata["metadata"]["indices"][changed] = case.metadata["metadata"]["indices"].pop(
            name
        )
        case.listing["metadata"]["indices"][changed] = case.listing["metadata"]["indices"].pop(name)
    else:
        mapping["properties"]["indexing_profile_id"] = {"type": "text"}
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)


@pytest.mark.parametrize(
    "fault",
    [
        "entry_copy",
        "lost_companion",
        "lost_parent",
        "companion_copy",
        "wrong_parent_nonce",
        "deployment",
    ],
)
async def test_source_pair_requires_retained_exact_objects(case: Any, fault: str) -> None:
    add_legacy(case, uuid4(), prefix="outside")
    cap = await case.issuer.observe(case.snapshot)
    companion = case.issuer.unmanaged(cap)
    if fault == "entry_copy":
        object.__setattr__(companion, "entries", (replace(companion.entries[0]),))
    elif fault == "lost_companion":
        case.issuer._unmanaged.clear()
    elif fault == "lost_parent":
        case.issuer._issued.clear()
    elif fault == "companion_copy":
        case.issuer._companions[cap] = replace(companion)
    elif fault == "wrong_parent_nonce":
        object.__setattr__(companion, "namespace_nonce", uuid4())
    else:
        object.__setattr__(companion, "original_deployment_sha256", "a" * 64)
    with pytest.raises(ValueError):
        case.issuer.assert_issued(cap)
    with pytest.raises(ValueError):
        case.issuer.assert_unmanaged_issued(companion)


@pytest.mark.parametrize("change", ["private", "aliases", "uuid"])
async def test_unmanaged_samples_must_be_complete_and_stable(
    case: Any, monkeypatch: Any, change: str
) -> None:
    name = add_legacy(case, uuid4(), prefix="outside")
    read = case.issuer._read
    calls = 0

    async def changing(path: str) -> bytes:
        nonlocal calls
        calls += 1
        if calls == 3:
            row = case.metadata["metadata"]["indices"][name]
            if change == "private":
                row["mappings"]["_doc"]["_meta"]["note"] = "changed-private"
            elif change == "aliases":
                row["aliases"] = ["outside-new-alias"]
            else:
                row["settings"]["index.uuid"] = "changedUUID"
                case.listing["metadata"]["indices"][name]["settings"]["index.uuid"] = "changedUUID"
        result: bytes = await read(path)
        return result

    monkeypatch.setattr(case.issuer, "_read", changing)
    with pytest.raises(ValueError):
        await case.issuer.observe(case.snapshot)
    assert not case.issuer._issued and not case.issuer._unmanaged


async def test_empty_companion_still_has_transitive_issuer_contract(case: Any) -> None:
    first = await case.issuer.observe(case.snapshot)
    empty = case.issuer.unmanaged(first)
    assert empty.entries == ()
    second = await case.issuer.observe(case.snapshot)
    assert second is not first and case.issuer.unmanaged(second) is not empty
    assert case.issuer.assert_unmanaged_issued(empty) is None
    object.__setattr__(empty, "namespace_nonce", uuid4())
    with pytest.raises(ValueError):
        case.issuer.assert_issued(first)
    assert case.issuer.assert_issued(second) is None


async def test_supported_uuid_shaped_prefix_is_private_unmanaged_not_a_grant(case: Any) -> None:
    prefix = "outside-" + str(uuid4())
    name = add_legacy(case, uuid4(), prefix=prefix)
    cap = await case.issuer.observe(case.snapshot)
    entry = case.issuer.unmanaged(cap).entries[0]
    assert (entry.name, entry.prefix, entry.reason) == (name, prefix, "outside_configured_prefix")
    assert cap.permissions.prefix == "rag"
    assert cap.permissions.namespaces == ((UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),)
    with pytest.raises(ValueError):
        cap.permissions.authorize("collector", "get", (name,))


def empty_selected(case: Any, *, new_processing: bool = False) -> tuple[UUID, UUID]:
    profile = uuid4()
    processing = uuid4() if new_processing else UUID(case.wire.PROCESSING)
    case.snapshot = replace(
        case.snapshot,
        indexing_profile_id=profile,
        document_processing_profile_id=processing,
        alias=f"rag-{processing}-{profile}-active",
        targets=(),
    )
    # Changing the snapshot requires a fresh genuine observation from its issuer.
    return profile, processing


@pytest.mark.parametrize("new_processing", [False, True])
async def test_selected_db_backed_pair_can_precede_its_first_physical_index(
    case: Any, new_processing: bool
) -> None:
    profile, processing = empty_selected(case, new_processing=new_processing)
    case.observed = await case.original.observe_deployment(case.snapshot)
    case.issuer = case.source.OriginalNamespaceSource(case.settings, case.original, case.observed)
    case.profiles.append((profile, "indexing"))
    if new_processing:
        case.profiles.append((processing, "document_processing"))
    cap = await case.issuer.observe(case.snapshot)
    assert set(cap.permissions.namespaces) == {
        (UUID(case.wire.PROFILE), UUID(case.wire.PROCESSING)),
        (profile, processing),
    }
    assert case.snapshot.alias in cap.permissions.aliases
    assert all({profile, processing} <= set(requested) for requested in case.db_requested)
    assert case.issuer.assert_issued(cap) is None
    assert case.issuer.unmanaged(cap).entries == ()
    assert case.db_calls == 2


@pytest.mark.parametrize("fault", ["missing", "wrong_kind", "disappears", "wrong_processing"])
async def test_empty_selected_namespace_requires_both_exact_stable_profile_kinds(
    case: Any, fault: str
) -> None:
    profile, processing = empty_selected(case, new_processing=True)
    case.observed = await case.original.observe_deployment(case.snapshot)
    case.issuer = case.source.OriginalNamespaceSource(case.settings, case.original, case.observed)
    case.profiles.extend([(profile, "indexing"), (processing, "document_processing")])
    if fault == "missing":
        case.profiles.pop(-2)
    elif fault == "wrong_kind":
        case.profiles[-2] = (profile, "generation")
    elif fault == "disappears":
        case.profile_passes = [case.profiles.copy(), case.profiles[:-2]]
    else:
        case.profiles[-1] = (processing, "indexing")
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer.observe(case.snapshot)


async def test_profile_absence_query_cannot_truncate_the_maximum_selected_scope(
    case: Any, monkeypatch: Any
) -> None:
    expected = {uuid4(): "indexing" for _ in range(130)}
    requested_limits = []

    class Connection:
        async def execute(self, statement: Any) -> Any:
            limit = int(statement.compile().params["param_1"])
            requested_limits.append(limit)
            rows = list(expected.items())[:limit]
            return SimpleNamespace(all=lambda: rows)

    class Engine:
        @asynccontextmanager
        async def connect(self) -> Any:
            yield Connection()

        async def dispose(self) -> None:
            pass

    monkeypatch.setattr(case.source, "create_engine", lambda _settings: Engine())
    assert await case.issuer._profiles(expected) == expected
    assert requested_limits == [131]


async def test_profile_scope_above_physical_plus_selected_bound_denies_before_sql(
    case: Any,
) -> None:
    with pytest.raises(ValueError, match="^original_namespace_unverified$"):
        await case.issuer._profiles({uuid4(): "indexing" for _ in range(131)})
    assert case.db_calls == 0


async def test_identical_live_configuration_inputs_parse_once(case: Any, monkeypatch: Any) -> None:
    calls: list[Path] = []

    def load(**kwargs: Any) -> Any:
        calls.append(kwargs["_env_file"])
        return case.settings.model_copy(deep=True)

    monkeypatch.setattr(case.source, "Settings", load)
    cap = await case.issuer.observe(case.snapshot)
    for _ in range(8):
        case.issuer.assert_issued(cap)
    assert calls == [case.source.PROJECT_ROOT / ".env"]


@pytest.mark.parametrize("changed_input", ["file", "environment"])
async def test_changed_live_configuration_never_uses_cached_validation(
    case: Any, monkeypatch: Any, changed_input: str
) -> None:
    import os

    calls = []
    path = case.source.PROJECT_ROOT / ".env"
    original_bytes = path.read_bytes()

    def load(**kwargs: Any) -> Any:
        calls.append(1)
        changed = path.read_bytes() != original_bytes or os.environ.get("SYNTHETIC_SOURCE_DRIFT")
        return case.settings.model_copy(
            update={"rag_index_store_id": "changed"} if changed else {}, deep=True
        )

    monkeypatch.setattr(case.source, "Settings", load)
    cap = await case.issuer.observe(case.snapshot)
    assert len(calls) == 1
    if changed_input == "file":
        path.write_bytes(original_bytes.replace(b"synthetic", b"different"))
    else:
        monkeypatch.setenv("SYNTHETIC_SOURCE_DRIFT", "1")
    with pytest.raises(ValueError):
        case.issuer.assert_issued(cap)
    assert len(calls) == 2
    # Failed refresh must not accept the changed source on another check.
    with pytest.raises(ValueError):
        case.issuer.assert_issued(cap)
    assert len(calls) == 3


@pytest.mark.parametrize("changed_input", ["file", "environment"])
async def test_configuration_inputs_changed_during_parse_deny_publication(
    case: Any, monkeypatch: Any, changed_input: str
) -> None:
    path = case.source.PROJECT_ROOT / ".env"

    def load(**kwargs: Any) -> Any:
        if changed_input == "file":
            path.write_bytes(path.read_bytes() + b"# changed while parsing\n")
        else:
            monkeypatch.setenv("SYNTHETIC_SOURCE_PARSE_RACE", "1")
        return case.settings.model_copy(deep=True)

    monkeypatch.setattr(case.source, "Settings", load)
    with pytest.raises(ValueError):
        await case.issuer.observe(case.snapshot)
    assert case.calls == [] and case.db_calls == 0
    assert case.issuer._issued == {}


async def test_current_settings_mutation_still_denies_cached_inputs(case: Any) -> None:
    cap = await case.issuer.observe(case.snapshot)
    case.settings.rag_index_store_id = "changed"
    with pytest.raises(ValueError):
        case.issuer.assert_issued(cap)


@pytest.mark.parametrize(
    "substitution", ["inputs", "clone", "nonce", "bytes", "context", "foreign", "foreign_state"]
)
async def test_only_same_source_issued_configuration_cache_can_be_reused(
    case: Any, substitution: str
) -> None:
    cap = await case.issuer.observe(case.snapshot)
    cache = case.issuer._configuration_inputs
    path = case.source.PROJECT_ROOT / ".env"
    if substitution == "inputs":
        case.issuer._configuration_inputs = case.issuer._configuration_input(path)
    elif substitution == "clone":
        case.issuer._configuration_inputs = replace(cache)
    elif substitution == "nonce":
        object.__setattr__(cache, "nonce", str(cache.nonce))
    elif substitution == "bytes":
        object.__setattr__(cache, "inputs", (cache.inputs[0], b"unparsed", *cache.inputs[2:]))
    elif substitution == "context":
        object.__setattr__(cache, "configuration", ("forged",))
    else:
        other = case.source.OriginalNamespaceSource(case.settings, case.original, case.observed)
        case.issuer._configuration_inputs = other._configuration_inputs
        if substitution == "foreign_state":
            case.issuer._configuration_tokens = other._configuration_tokens
    with pytest.raises(ValueError):
        case.issuer.assert_issued(cap)
