"""One-shot source for five reviewed, complete public 9.5.2 software packets.

No descriptor is learned from a caller DTO. Only owned fixed read-only helpers
are admitted; original packets and child associations remain private in RAM.
This source issues software provenance, never system-index/control authority.
"""

from dataclasses import dataclass, fields
from hashlib import sha256
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel, SecretStr

from ai_workshop.config import Settings
from ai_workshop.infrastructure.local.control_process_windows import (
    ChildIdentity,
    LocalProcessResult,
    WindowsControlProcess,
)
from ai_workshop.labs.rag.indexing.access_epoch_native import (
    ORIGINAL_IMAGE,
    OriginalAccessEpochPreflight,
    OriginalDeploymentObservation,
    OriginalImageReference,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import DOCKER_EXE
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

_CWD = Path(__file__).resolve().parents[6]
_ENV = {"SystemRoot": r"C:\Windows", "WINDIR": r"C:\Windows"}
_ENDPOINT = "npipe:////./pipe/dockerDesktopLinuxEngine"
_SECURITY_JAR = "/usr/share/elasticsearch/modules/x-pack-security/x-pack-security-9.5.2.jar"
_CORE_JAR = "/usr/share/elasticsearch/lib/elasticsearch-9.5.2.jar"
_CLASSES = (
    (_SECURITY_JAR, "org.elasticsearch.xpack.security.support.SecuritySystemIndices"),
    (
        _SECURITY_JAR,
        "org.elasticsearch.xpack.security.support.SecuritySystemIndices$SecurityMainIndexMappingVersion",
    ),
    (_CORE_JAR, "org.elasticsearch.indices.SystemIndexDescriptor"),
    (_CORE_JAR, "org.elasticsearch.indices.SystemIndexDescriptor$Builder"),
    (_CORE_JAR, "org.elasticsearch.cluster.metadata.IndexMetadata"),
)
# Reviewed whole public software packets, not index/response/private-data hashes.
_PINS = (
    "d4bbebeeff78b6040e3603357db62e0200b857c86cdd843f063b57fba2b63f75",
    "ec061b11c4bcc1f76319fef67ce98ee0c25f46280abe0df87376340204e3b9e6",
    "b1ab9754470e368c281e598a2f482f0d3221896a45d3707704f4181a6ee18d67",
    "2c344b4f9438018eecb29655af69867589f143d5c75917e339bd7bd39bf7498e",
    "45fa8fe59a199f4e48810986f84666a1c55227986e03405c365c5f26c86c6637",
)
_PACKET_LIMIT = 1024 * 1024
_AGGREGATE_LIMIT = 4 * _PACKET_LIMIT


def _denied() -> ValueError:
    return ValueError("security_descriptor_source_unverified")


@dataclass(frozen=True, slots=True, eq=False)
class ObservedSecurityDescriptor:
    nonce: UUID
    snapshot_sha256: str
    original_deployment_sha256: str
    image: OriginalImageReference
    source_contract: str = "es_9_5_2_main_security_v1"
    primary_name: str = ".security-7"
    alias_name: str = ".security"
    index_format_setting: str = "index.format"
    index_format: int = 6
    primary_shards: int = 1
    auto_expand_replicas: str = "0-1"
    hidden: bool = True
    security_version_key: str = "security-version"
    security_version: str = "8.14.0"
    mapping_version_key: str = "managed_index_mappings_version"
    mapping_version: int = 5


def _settings_signature(value: Settings) -> object:
    def primitive(item: object) -> object:
        if isinstance(item, SecretStr):
            return item.get_secret_value()
        if isinstance(item, BaseModel):
            return tuple((name, primitive(getattr(item, name))) for name in type(item).model_fields)
        if isinstance(item, (Path, UUID)):
            return str(item)
        if type(item) in (list, tuple):
            return tuple(primitive(x) for x in cast(list[object] | tuple[object, ...], item))
        if type(item) is dict:
            return tuple(
                (key, primitive(child)) for key, child in cast(dict[object, object], item).items()
            )
        if item is None or type(item) in (str, int, bool, float):
            return item
        raise _denied()

    return primitive(value)


def _signature(value: ObservedSecurityDescriptor) -> tuple[object, ...]:
    if type(value.nonce) is not UUID or type(value.image) is not OriginalImageReference:
        raise _denied()
    primitive: list[object] = [str(value.nonce), id(value.image)]
    for field in fields(value):
        child = getattr(value, field.name)
        if field.name in ("nonce", "image"):
            continue
        if type(child) not in (str, int, bool):
            raise _denied()
        primitive.append((field.name, type(child), child))
    for field in fields(value.image):
        child = getattr(value.image, field.name)
        if type(child) is not str:
            raise _denied()
        primitive.append(child)
    return tuple(primitive)


def _capture_signature(captures: tuple[tuple[bytes, ChildIdentity], ...]) -> tuple[object, ...]:
    result: list[object] = []
    for packet, child in captures:
        if (
            type(packet) is not bytes
            or type(child) is not ChildIdentity
            or type(child.pid) is not int
            or child.pid <= 0
            or type(child.creation_time) is not str
            or not child.creation_time.isascii()
            or not child.creation_time.isdecimal()
            or int(child.creation_time) <= 0
            or type(child.job_id) is not UUID
        ):
            raise _denied()
        result.append(
            (
                sha256(packet).hexdigest(),
                id(child),
                child.pid,
                child.creation_time,
                str(child.job_id),
            )
        )
    return tuple(result)


class OriginalSecurityDescriptorSource:
    def __init__(
        self,
        settings: Settings,
        original: OriginalAccessEpochPreflight,
        observation: OriginalDeploymentObservation,
        process: WindowsControlProcess,
    ) -> None:
        self.settings, self.original = settings, original
        self.observation, self.process = observation, process
        self._attempted = False
        self._cleanup_unverified = False
        self._issued: dict[ObservedSecurityDescriptor, tuple[object, ...]] = {}
        self._captures: dict[
            ObservedSecurityDescriptor, tuple[tuple[bytes, ChildIdentity], ...]
        ] = {}
        self._capture_signatures: dict[ObservedSecurityDescriptor, tuple[object, ...]] = {}
        try:
            if (
                type(settings) is not Settings
                or type(original) is not OriginalAccessEpochPreflight
                or type(observation) is not OriginalDeploymentObservation
                or type(process) is not WindowsControlProcess
                or original.settings is not settings
                or settings.environment != "local"
                or observation.image.image_id != ORIGINAL_IMAGE
            ):
                raise _denied()
            original.assert_observed(observation)
            self._objects = (settings, original, observation, process)
            self._settings = _settings_signature(settings)
            self._observer_io = (original.executor, original.reader)
            self._process = (
                process._native,
                process._limit,
                process._max_wait_ms,
                process._input_limit,
            )
            self._guard()
        except Exception:
            raise _denied() from None

    @property
    def cleanup_unverified(self) -> bool:
        """Body-free diagnostic only; never a source/control capability."""
        return self._cleanup_unverified

    def _guard(self, snapshot: AliasOperationSnapshot | None = None) -> None:
        if (
            any(
                a is not b
                for a, b in zip(
                    self._objects,
                    (self.settings, self.original, self.observation, self.process),
                    strict=True,
                )
            )
            or self.original.settings is not self.settings
            or _settings_signature(self.settings) != self._settings
            or self.original.executor is not self._observer_io[0]
            or self.original.reader is not self._observer_io[1]
            or self.process._native is not self._process[0]
            or (self.process._limit, self.process._max_wait_ms, self.process._input_limit)
            != self._process[1:]
            or type(self.process._limit) is not int
            or not 1 <= self.process._limit <= _PACKET_LIMIT
            or self.observation.image.image_id != ORIGINAL_IMAGE
        ):
            raise _denied()
        self.original.assert_observed(self.observation)
        if snapshot is not None and (
            type(snapshot) is not AliasOperationSnapshot
            or snapshot.sha256 != self.observation.snapshot_sha256
            or snapshot.cluster_uuid != self.observation.identity.cluster_uuid
            or snapshot.store_id != self.settings.rag_index_store_id
        ):
            raise _denied()

    async def _identity(self, snapshot: AliasOperationSnapshot) -> None:
        self._guard(snapshot)
        actual = await self.original.observe_original(snapshot)
        self._guard(snapshot)
        if (
            actual != self.observation.identity
            or type(actual) is not type(self.observation.identity)
            or self.original.image_reference != self.observation.image
            or self.original.original_origin != self.observation.origin
        ):
            raise _denied()

    def _capture(self, classpath: str, class_name: str) -> tuple[bytes, ChildIdentity]:
        argv = (
            DOCKER_EXE,
            "--host",
            _ENDPOINT,
            "exec",
            self.observation.identity.container_id,
            "/usr/share/elasticsearch/jdk/bin/javap",
            "-c",
            "-p",
            "-constants",
            "-classpath",
            classpath,
            class_name,
        )
        token = self.process.create_suspended(argv, dict(_ENV), _CWD)
        capture: tuple[bytes, ChildIdentity] | None = None
        failure: BaseException | None = None
        try:
            self.process.resume(token)
            result = self.process.wait(token, min(30000, self.process._max_wait_ms))
            if (
                type(result) is not LocalProcessResult
                or result.child is not token.child
                or type(result.exit_code) is not int
                or result.exit_code != 0
                or type(result.stdout) is not bytes
                or type(result.stderr) is not bytes
                or result.stderr
                or not 0 < len(result.stdout) <= _PACKET_LIMIT
            ):
                raise _denied()
            # Strict UTF8; no stripping, newline insertion, BOM, whitespace or code rewriting.
            result.stdout.decode("utf-8", errors="strict")
            capture = result.stdout, result.child
        except BaseException as exc:
            failure = exc
        finally:
            try:
                self.process.close(token)
            except BaseException as exc:
                self._cleanup_unverified = True
                # Cleanup must not mask the primary cancellation/interruption.
                # If only cleanup interrupts, propagate that interruption itself.
                if failure is None or (
                    isinstance(failure, Exception) and not isinstance(exc, Exception)
                ):
                    failure = exc
        if failure is not None:
            raise failure from None
        if capture is None:
            raise _denied()
        return capture

    async def observe(self, snapshot: AliasOperationSnapshot) -> ObservedSecurityDescriptor:
        if self._attempted:
            raise _denied()
        self._attempted = True  # Lost ACK/cancellation/errors consume the whole attempt.
        try:
            await self._identity(snapshot)
            captures: list[tuple[bytes, ChildIdentity]] = []
            aggregate = 0
            for (classpath, class_name), expected in zip(_CLASSES, _PINS, strict=True):
                self._guard(snapshot)
                packet, child = self._capture(classpath, class_name)
                aggregate += len(packet)
                normalized = packet.replace(b"\r\n", b"\n")
                if aggregate > _AGGREGATE_LIMIT or sha256(normalized).hexdigest() != expected:
                    raise _denied()
                captures.append((packet, child))
                self._guard(snapshot)
            await self._identity(snapshot)
            result = ObservedSecurityDescriptor(
                uuid4(),
                snapshot.sha256,
                self.observation.identity.deployment_sha256,
                self.observation.image,
            )
            signature = _signature(result)
            held = tuple(captures)
            capture_signature = _capture_signature(held)
            self._issued[result] = signature
            self._captures[result] = held
            self._capture_signatures[result] = capture_signature
            return result
        except Exception:
            raise _denied() from None

    def assert_issued(self, value: object) -> None:
        try:
            self._guard()
            if (
                type(value) is not ObservedSecurityDescriptor
                or value not in self._issued
                or _signature(value) != self._issued[value]
                or len(self._captures[value]) != 5
                or _capture_signature(self._captures[value]) != self._capture_signatures[value]
            ):
                raise _denied()
        except Exception:
            raise _denied() from None
