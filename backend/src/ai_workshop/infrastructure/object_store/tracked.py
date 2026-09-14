from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from uuid import UUID

from ai_workshop.labs.rag.ingestion.artifact_contracts import (
    ArtifactBinding,
    ArtifactClaim,
    ArtifactPublication,
    ArtifactRole,
    ArtifactTrackingError,
    VerifiedArtifact,
)
from ai_workshop.platform.assets.storage import StoredObject

RAG_ARTIFACT_KEY_CONTRACT_VERSION = 1

_BINDING_MARKER = ".ai-workshop-store.json"
_BINDING_MARKER_MAX_BYTES = 4096
_REPARSE_POINT_ATTRIBUTE = 0x400
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ArtifactStoreError(ArtifactTrackingError):
    def __init__(
        self,
        code: str,
        *,
        writer_finished: bool = False,
        temporary_absent: bool = False,
    ) -> None:
        self.writer_finished = writer_finished
        self.temporary_absent = temporary_absent
        super().__init__(code)


class TrackedLocalArtifactStore:
    def __init__(self, root: Path, binding: ArtifactBinding) -> None:
        if not isinstance(root, Path) or not isinstance(binding, ArtifactBinding):
            raise ArtifactStoreError("artifact_store_configuration_invalid")
        self.root = root.absolute()
        self.binding = binding

    def verify_binding(self) -> None:
        self._validate_root()
        marker = self._exact_child(self.root, _BINDING_MARKER)
        if marker is None:
            raise ArtifactStoreError("artifact_binding_missing")
        self._require_plain_file(marker)
        try:
            with marker.open("rb") as marker_file:
                raw_marker = marker_file.read(_BINDING_MARKER_MAX_BYTES + 1)
        except OSError:
            raise ArtifactStoreError("artifact_binding_invalid") from None
        if len(raw_marker) > _BINDING_MARKER_MAX_BYTES:
            raise ArtifactStoreError("artifact_binding_invalid")
        try:
            value = json.loads(raw_marker.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ArtifactStoreError("artifact_binding_invalid") from None
        if type(value) is not dict or set(value) != {
            "schema_version",
            "store_id",
            "binding_id",
        }:
            raise ArtifactStoreError("artifact_binding_invalid")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ArtifactStoreError("artifact_binding_invalid")
        if type(value["store_id"]) is not str or type(value["binding_id"]) is not str:
            raise ArtifactStoreError("artifact_binding_invalid")
        try:
            marker_binding_id = UUID(value["binding_id"])
        except ValueError:
            raise ArtifactStoreError("artifact_binding_invalid") from None
        if str(marker_binding_id) != value["binding_id"]:
            raise ArtifactStoreError("artifact_binding_invalid")
        if (
            value["store_id"] != self.binding.store_id
            or marker_binding_id != self.binding.binding_id
        ):
            raise ArtifactStoreError("artifact_binding_mismatch")

    async def publish(
        self, claim: ArtifactClaim, content: bytes
    ) -> tuple[ArtifactPublication, bytes]:
        self._validate_claim(claim, content)
        self.verify_binding()
        canonical = self._object_path(claim.canonical_key, create_parents=True)
        temporary = self._object_path(claim.temporary_key, create_parents=False)
        if canonical is not None:
            raise ArtifactStoreError("artifact_canonical_conflict")
        if temporary is not None:
            raise ArtifactStoreError("artifact_temporary_conflict")

        canonical = self.root.joinpath(*claim.canonical_key.split("/"))
        temporary = self.root.joinpath(*claim.temporary_key.split("/"))
        try:
            temporary_file = temporary.open("xb")
        except FileExistsError:
            raise ArtifactStoreError("artifact_temporary_conflict") from None
        except OSError:
            raise ArtifactStoreError("artifact_io_failed") from None

        writer_finished = False
        failure_code: str | None = None
        observed: bytes | None = None
        try:
            temporary_identity = self._identity(os.fstat(temporary_file.fileno()))
        except OSError:
            temporary_file.close()
            raise ArtifactStoreError(
                "artifact_io_failed", writer_finished=temporary_file.closed
            ) from None
        try:
            try:
                with temporary_file:
                    temporary_file.write(content)
                    temporary_file.flush()
                    os.fsync(temporary_file.fileno())
            finally:
                writer_finished = temporary_file.closed

            self.verify_binding()
            self._require_safe_object_path(temporary)
            self._ensure_missing_canonical(canonical)
            try:
                os.link(temporary, canonical)
            except FileExistsError:
                raise ArtifactStoreError("artifact_canonical_conflict") from None

            self.verify_binding()
            self._require_safe_object_path(canonical)
            observed = self._read_exact(canonical, claim.proposed_size)
            if hashlib.sha256(observed).hexdigest() != claim.proposed_sha256:
                raise ArtifactStoreError("artifact_integrity_mismatch")
        except ArtifactStoreError as error:
            failure_code = error.code
        except OSError:
            failure_code = "artifact_io_failed"

        temporary_absent = self._remove_owned_temporary(
            claim.temporary_key, temporary, temporary_identity
        )
        if not temporary_absent and failure_code is None:
            failure_code = "artifact_temporary_cleanup_failed"
        if failure_code is not None:
            raise ArtifactStoreError(
                failure_code,
                writer_finished=writer_finished,
                temporary_absent=temporary_absent,
            ) from None
        if observed is None:
            raise ArtifactStoreError(
                "artifact_io_failed",
                writer_finished=writer_finished,
                temporary_absent=temporary_absent,
            )
        publication = ArtifactPublication(
            claim=claim,
            size=len(observed),
            sha256=hashlib.sha256(observed).hexdigest(),
        )
        return publication, observed

    async def read_verified(self, artifact: VerifiedArtifact) -> bytes:
        self._validate_verified_artifact(artifact)
        self.verify_binding()
        path = self._object_path(artifact.canonical_key, create_parents=False)
        if path is None:
            raise ArtifactStoreError("artifact_missing")
        observed = self._read_exact(path, artifact.size)
        if hashlib.sha256(observed).hexdigest() != artifact.sha256:
            raise ArtifactStoreError("artifact_integrity_mismatch")
        self.verify_binding()
        return observed

    async def inspect_key(self, key: str) -> StoredObject | None:
        self._validate_key(key)
        self.verify_binding()
        path = self._object_path(key, create_parents=False)
        if path is None:
            return None
        size, digest = self._describe(path)
        self.verify_binding()
        return StoredObject(key=key, size=size, sha256=digest)

    def _validate_root(self) -> None:
        try:
            root_status = self.root.lstat()
        except OSError:
            raise ArtifactStoreError("artifact_store_root_invalid") from None
        if self._is_reparse(root_status):
            raise ArtifactStoreError("artifact_reparse_path")
        if not stat.S_ISDIR(root_status.st_mode):
            raise ArtifactStoreError("artifact_store_root_invalid")
        try:
            resolved = self.root.resolve(strict=True)
        except OSError:
            raise ArtifactStoreError("artifact_store_root_invalid") from None
        if os.path.normcase(str(resolved)) != os.path.normcase(str(self.root)):
            raise ArtifactStoreError("artifact_path_alias")

    def _exact_child(self, parent: Path, name: str) -> Path | None:
        try:
            entries = tuple(os.scandir(parent))
        except OSError:
            raise ArtifactStoreError("artifact_io_failed") from None
        for entry in entries:
            if entry.name.casefold() == name.casefold() and entry.name != name:
                raise ArtifactStoreError("artifact_path_alias")
        return parent / name if any(entry.name == name for entry in entries) else None

    def _object_path(self, key: str, *, create_parents: bool) -> Path | None:
        parts = key.split("/")
        parent = self.root
        for part in parts[:-1]:
            child = self._exact_child(parent, part)
            if child is None:
                if not create_parents:
                    return None
                try:
                    (parent / part).mkdir()
                except FileExistsError:
                    child = self._exact_child(parent, part)
                    if child is None:
                        raise ArtifactStoreError("artifact_io_failed") from None
                except OSError:
                    raise ArtifactStoreError("artifact_io_failed") from None
                else:
                    child = parent / part
            self._require_plain_directory(child)
            parent = child
        child = self._exact_child(parent, parts[-1])
        if child is not None:
            self._require_plain_file(child)
        return child

    def _require_safe_object_path(self, path: Path) -> None:
        parent = self.root
        relative = path.relative_to(self.root)
        for part in relative.parts[:-1]:
            child = self._exact_child(parent, part)
            if child is None:
                raise ArtifactStoreError("artifact_io_failed")
            self._require_plain_directory(child)
            parent = child
        child = self._exact_child(parent, relative.parts[-1])
        if child is None:
            raise ArtifactStoreError("artifact_io_failed")
        self._require_plain_file(child)

    def _ensure_missing_canonical(self, path: Path) -> None:
        self._require_plain_directory(path.parent)
        child = self._exact_child(path.parent, path.name)
        if child is not None:
            self._require_plain_file(child)
            raise ArtifactStoreError("artifact_canonical_conflict")

    def _require_plain_directory(self, path: Path) -> None:
        status = self._status(path)
        if self._is_reparse(status):
            raise ArtifactStoreError("artifact_reparse_path")
        if not stat.S_ISDIR(status.st_mode):
            raise ArtifactStoreError("artifact_path_invalid")

    def _require_plain_file(self, path: Path) -> None:
        status = self._status(path)
        if self._is_reparse(status):
            raise ArtifactStoreError("artifact_reparse_path")
        if not stat.S_ISREG(status.st_mode):
            raise ArtifactStoreError("artifact_path_invalid")

    def _status(self, path: Path) -> os.stat_result:
        try:
            return path.lstat()
        except OSError:
            raise ArtifactStoreError("artifact_io_failed") from None

    @staticmethod
    def _is_reparse(status: os.stat_result) -> bool:
        attributes = getattr(status, "st_file_attributes", 0)
        return stat.S_ISLNK(status.st_mode) or bool(
            attributes & _REPARSE_POINT_ATTRIBUTE
        )

    def _validate_claim(self, claim: ArtifactClaim, content: bytes) -> None:
        if not isinstance(claim, ArtifactClaim) or type(content) is not bytes:
            raise ArtifactStoreError("artifact_claim_invalid")
        self._validate_common_artifact_fields(
            projection_id=claim.projection_id,
            role=claim.role,
            binding=claim.binding,
            canonical_key=claim.canonical_key,
        )
        if not all(
            isinstance(value, UUID)
            for value in (claim.bundle_id, claim.slot_id, claim.attempt_id, claim.job_id)
        ):
            raise ArtifactStoreError("artifact_claim_invalid")
        expected_temporary = (
            f"rag/{claim.role.value}/.{claim.projection_id}.json."
            f"{claim.attempt_id.hex}.tmp"
        )
        if claim.temporary_key != expected_temporary:
            raise ArtifactStoreError("artifact_key_invalid")
        self._validate_key(claim.temporary_key)
        if (
            type(claim.proposed_size) is not int
            or claim.proposed_size < 0
            or _SHA256_PATTERN.fullmatch(claim.proposed_sha256) is None
        ):
            raise ArtifactStoreError("artifact_claim_invalid")
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != claim.proposed_size or digest != claim.proposed_sha256:
            raise ArtifactStoreError("artifact_claim_mismatch")

    def _validate_verified_artifact(self, artifact: VerifiedArtifact) -> None:
        if not isinstance(artifact, VerifiedArtifact):
            raise ArtifactStoreError("artifact_verification_invalid")
        self._validate_common_artifact_fields(
            projection_id=artifact.projection_id,
            role=artifact.role,
            binding=artifact.binding,
            canonical_key=artifact.canonical_key,
        )
        if not all(
            isinstance(value, UUID)
            for value in (artifact.bundle_id, artifact.slot_id, artifact.job_id)
        ):
            raise ArtifactStoreError("artifact_verification_invalid")
        if (
            type(artifact.size) is not int
            or artifact.size < 0
            or _SHA256_PATTERN.fullmatch(artifact.sha256) is None
        ):
            raise ArtifactStoreError("artifact_verification_invalid")

    def _validate_common_artifact_fields(
        self,
        *,
        projection_id: UUID,
        role: ArtifactRole,
        binding: ArtifactBinding,
        canonical_key: str,
    ) -> None:
        if binding != self.binding:
            raise ArtifactStoreError("artifact_binding_mismatch")
        if not isinstance(projection_id, UUID) or not isinstance(role, ArtifactRole):
            raise ArtifactStoreError("artifact_claim_invalid")
        expected_canonical = f"rag/{role.value}/{projection_id}.json"
        if canonical_key != expected_canonical:
            raise ArtifactStoreError("artifact_key_invalid")
        self._validate_key(canonical_key)

    @staticmethod
    def _validate_key(key: str) -> None:
        if type(key) is not str or not key or "\\" in key:
            raise ArtifactStoreError("artifact_key_invalid")
        path = Path(key)
        if path.is_absolute() or any(part in {"", ".", ".."} for part in key.split("/")):
            raise ArtifactStoreError("artifact_key_invalid")
        parts = key.split("/")
        if len(parts) != 3 or parts[0] != "rag" or parts[1] not in {
            role.value for role in ArtifactRole
        }:
            raise ArtifactStoreError("artifact_key_invalid")
        filename = parts[2]
        canonical_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\.json"
        )
        temporary_pattern = re.compile(
            rf"\.{canonical_pattern.pattern}\.[0-9a-f]{{32}}\.tmp"
        )
        if (
            canonical_pattern.fullmatch(filename) is None
            and temporary_pattern.fullmatch(filename) is None
        ):
            raise ArtifactStoreError("artifact_key_invalid")

    @staticmethod
    def _read_exact(path: Path, expected_size: int) -> bytes:
        try:
            with path.open("rb") as source:
                content = source.read(expected_size + 1)
        except OSError:
            raise ArtifactStoreError("artifact_io_failed") from None
        if len(content) != expected_size:
            raise ArtifactStoreError("artifact_integrity_mismatch")
        return content

    @staticmethod
    def _describe(path: Path) -> tuple[int, str]:
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as source:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    size += len(block)
                    digest.update(block)
        except OSError:
            raise ArtifactStoreError("artifact_io_failed") from None
        return size, digest.hexdigest()

    @staticmethod
    def _identity(status: os.stat_result) -> tuple[int, int]:
        return status.st_dev, status.st_ino

    def _remove_owned_temporary(
        self, key: str, path: Path, expected_identity: tuple[int, int]
    ) -> bool:
        try:
            self.verify_binding()
            self._require_safe_object_path(path)
            if self._identity(self._status(path)) != expected_identity:
                return False
            path.unlink()
            self.verify_binding()
            return self._object_path(key, create_parents=False) is None
        except (ArtifactStoreError, OSError):
            return False
