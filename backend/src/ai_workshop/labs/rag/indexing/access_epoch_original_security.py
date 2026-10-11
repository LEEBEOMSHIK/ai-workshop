"""Original hidden security metadata absence; no passwords or keys are changed."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ai_workshop.labs.rag.indexing.access_epoch_types import (
    OriginalDeploymentIdentity,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import ElasticsearchReader
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot, utc_text

_PATH = "/_cat/indices/.security*?expand_wildcards=all&format=json&h=index"


def _denied() -> ValueError:
    return ValueError("original_security_absence_unverified")


class OriginalSecurityIdentityPort(Protocol):
    async def observe_original(
        self, snapshot: AliasOperationSnapshot
    ) -> OriginalDeploymentIdentity: ...


@dataclass(frozen=True, slots=True, eq=False)
class ObservedOriginalSecurityAbsent:
    original: OriginalDeploymentIdentity
    manifest_json: str


class OriginalSecurityAbsenceReader:
    def __init__(self, identity: OriginalSecurityIdentityPort, reader: ElasticsearchReader) -> None:
        self.identity, self.reader = identity, reader
        self._issued: dict[ObservedOriginalSecurityAbsent, str] = {}

    async def observe(self, snapshot: AliasOperationSnapshot) -> ObservedOriginalSecurityAbsent:
        try:
            before = await self.identity.observe_original(snapshot)
            if (
                type(before) is not OriginalDeploymentIdentity
                or before.cluster_uuid != snapshot.cluster_uuid
            ):
                raise _denied()
            value = await self.reader.read(_PATH)
            if type(value) is not list or value:
                raise _denied()
            after = await self.identity.observe_original(snapshot)
            if type(after) is not OriginalDeploymentIdentity or after != before:
                raise _denied()
            result = ObservedOriginalSecurityAbsent(
                before,
                canonical_json(
                    {
                        "schema_version": 1,
                        "observation": "original_hidden_security_indices_empty",
                        "container_id": before.container_id,
                        "daemon_sha256": before.daemon_sha256,
                        "cluster_uuid": before.cluster_uuid,
                        "original_deployment_sha256": before.deployment_sha256,
                        "observed_at": utc_text(datetime.now(UTC)),
                    }
                ),
            )
            self._issued[result] = result.manifest_json
            return result
        except Exception:
            raise _denied() from None

    def assert_original(self, observation: object, original: OriginalDeploymentIdentity) -> None:
        if (
            type(observation) is not ObservedOriginalSecurityAbsent
            or self._issued.get(observation) != observation.manifest_json
            or type(original) is not OriginalDeploymentIdentity
            or observation.original != original
        ):
            raise _denied()
