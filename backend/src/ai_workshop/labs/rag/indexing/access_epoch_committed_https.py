"""Source-owned committed credentials and TLS for the fixed HTTPS reader.

This returns private ordinary data, not a fresh server observation. A phase
source must bracket every transport with new reads and retain its own issuance.
"""

import json
from dataclasses import dataclass
from hashlib import sha256
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.labs.rag.indexing.access_epoch_committed_tls import NativeCommittedTlsReader
from ai_workshop.labs.rag.indexing.access_epoch_https_read import (
    SecuredHttpsKey,
    SecuredHttpsReadCatalog,
)
from ai_workshop.labs.rag.indexing.access_epoch_keys import KEY_ROLES
from ai_workshop.labs.rag.indexing.access_epoch_persisted_auth import decode_committed_auth_policy
from ai_workshop.labs.rag.indexing.access_epoch_secured_read import (
    NativeSecuredReadSource,
    SecuredReadBinding,
    _Sample,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import CutoverActionKind, canonical_json


def _denied() -> ValueError:
    return ValueError("committed_https_material_denied")


@dataclass(frozen=True, slots=True, repr=False)
class _CommittedHttpsMaterial:
    catalog: SecuredHttpsReadCatalog
    phase: str
    sample: _Sample


async def _read_committed_https_catalog(
    source: NativeSecuredReadSource,
    binding: SecuredReadBinding,
    reader: NativeCommittedTlsReader,
) -> _CommittedHttpsMaterial:
    try:
        if (
            type(source) is not NativeSecuredReadSource
            or type(binding) is not SecuredReadBinding
            or type(reader) is not NativeCommittedTlsReader
        ):
            raise _denied()
        origin = NativeCommittedTlsReader._memory(reader)
        if origin.source is not source or origin.binding is not binding:
            raise _denied()
        NativeSecuredReadSource._assert_committed_dependencies(source)
        NativeSecuredReadSource.assert_bound(source, binding)
        material = await NativeCommittedTlsReader._private_read_http_material(
            reader, source, binding
        )
        NativeSecuredReadSource._assert_committed_dependencies(source)
        NativeSecuredReadSource.assert_bound(source, binding)
        sample = material.sample
        prepared = sample.state.prepared
        if prepared is None or sample.evidence.binding != prepared.binding:
            raise _denied()
        facts = json.loads(sample.evidence.proof_facts_json)
        manifests = dict(sample.evidence.manifests)
        if manifests["tls_public_ca"] != material.manifest_json:
            raise _denied()
        parent = next(
            row
            for row in sample.state.actions
            if row.action.kind is CutoverActionKind.ISSUE_ROLE_KEY
        )
        group = json.loads(parent.manifest_json or "null")
        if tuple(row.action.role for row, _ in sample.credentials) != KEY_ROLES:
            raise _denied()
        key_ids = tuple((row.action.role, envelope.key_id) for row, envelope in sample.credentials)
        permissions = decode_committed_auth_policy(
            manifests["auth_policy"].encode(),
            prefix=source._settings.elasticsearch_index_prefix,
            epoch_id=binding.epoch_id,
            execution_id=binding.execution_id,
            container_id=facts["new_container_id"],
            key_ids=key_ids,
        )
        if prepared.binding.claim.snapshot.alias not in permissions.aliases:
            raise _denied()
        keys = []
        for row, envelope in sample.credentials:
            role, result = row.action.role, row.result
            descriptor_sha = sha256(
                canonical_json(dict(permissions.descriptor(role))).encode()
            ).hexdigest()
            if (
                row.outcome != "settled"
                or result is None
                or result.result != "issued"
                or result.role != role
                or result.issuance_id != row.action.issuance_id
                or row.action.execution_id != binding.execution_id
                or row.action.parent_action_id != parent.action.action_id
                or row.action.executor_generation != sample.state.executor_generation
                or row.action.permissions_sha256 != descriptor_sha
                or result.permissions_sha256 != descriptor_sha
                or group["permissions"][role] != descriptor_sha
                or group["issuances"][role] != str(row.action.issuance_id)
                or group["keys"][role] != result.key_id
                or envelope.key_id != result.key_id
                or envelope.role != role
                or envelope.epoch_id != binding.epoch_id
                or envelope.ordinal != binding.ordinal
                or UUID(prepared.binding.access_epoch_id) != binding.epoch_id
            ):
                raise _denied()
            keys.append(
                SecuredHttpsKey(
                    role,
                    envelope.key_id,
                    f"ai-workshop-{binding.epoch_id}-{role}-{row.action.issuance_id}",
                    SecretStr(envelope.secret.get_secret_value()),
                )
            )
        catalog = SecuredHttpsReadCatalog(
            binding.epoch_id, permissions, material.ca_pem, material.leaf_sha256, tuple(keys)
        )
        NativeCommittedTlsReader._guard(reader)
        return _CommittedHttpsMaterial(catalog, material.phase, sample)
    except Exception:
        raise _denied() from None
