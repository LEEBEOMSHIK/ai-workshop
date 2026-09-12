import base64
import binascii
import hashlib
import hmac
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from ai_workshop.labs.rag.generation.domain import ConversationRole, ConversationTurn


class ScopedTurnVerification(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    SCOPE_CHANGED = "scope_changed"


@dataclass(frozen=True, slots=True)
class ConversationScopeBinding:
    domain_id: UUID
    connection_version_id: UUID
    workspace_ids: tuple[UUID, ...]
    folder_ids: tuple[UUID, ...]
    document_ids: tuple[UUID, ...] | None = None
    scope_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if not self.workspace_ids:
            raise ValueError("A conversation scope requires a workspace.")
        if self.document_ids is not None and not self.document_ids:
            raise ValueError("A selected conversation scope requires a document.")
        if (self.document_ids is None) != (self.scope_fingerprint is None):
            raise ValueError(
                "A selected conversation scope requires its server fingerprint."
            )
        if self.document_ids is not None:
            object.__setattr__(
                self,
                "document_ids",
                self._normalized(self.document_ids),
            )

    @staticmethod
    def _normalized(values: tuple[UUID, ...]) -> tuple[UUID, ...]:
        return tuple(sorted(set(values), key=str))

    @property
    def normalized_workspace_ids(self) -> tuple[UUID, ...]:
        return self._normalized(self.workspace_ids)

    @property
    def normalized_folder_ids(self) -> tuple[UUID, ...]:
        return self._normalized(self.folder_ids)

    @property
    def normalized_document_ids(self) -> tuple[UUID, ...] | None:
        if self.document_ids is None:
            return None
        return self._normalized(self.document_ids)

    @property
    def selection_mode(self) -> str:
        return "selected_documents" if self.document_ids is not None else "unrestricted"


class ConversationTurnSigner:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("Conversation signing requires at least 32 secret bytes.")
        self.secret = secret

    def sign(
        self,
        *,
        content: str,
        actor_id: UUID,
        turn_id: UUID,
        configuration_version_id: UUID,
    ) -> str:
        digest = hmac.new(
            self.secret,
            self._message(
                content=content,
                actor_id=actor_id,
                turn_id=turn_id,
                configuration_version_id=configuration_version_id,
            ),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def verify(
        self,
        turn: ConversationTurn,
        *,
        actor_id: UUID,
        configuration_version_id: UUID,
    ) -> bool:
        if (
            turn.role is not ConversationRole.ASSISTANT
            or turn.turn_id is None
            or turn.validation_token is None
        ):
            return False
        expected = self.sign(
            content=turn.content,
            actor_id=actor_id,
            turn_id=turn.turn_id,
            configuration_version_id=configuration_version_id,
        )
        return hmac.compare_digest(turn.validation_token, expected)

    def sign_scoped(
        self,
        *,
        content: str,
        actor_id: UUID,
        turn_id: UUID,
        configuration_version_id: UUID,
        scope: ConversationScopeBinding,
    ) -> str:
        turn_digest = hashlib.sha256(
            self._message(
                content=content,
                actor_id=actor_id,
                turn_id=turn_id,
                configuration_version_id=configuration_version_id,
            )
        ).digest()
        scope_digest = hashlib.sha256(self._scope_message(scope)).digest()
        envelope = self._scoped_envelope(
            selection_mode=scope.selection_mode,
            turn_digest=turn_digest,
            scope_digest=scope_digest,
        )
        signature = hmac.new(self.secret, envelope, hashlib.sha256).digest()
        return ".".join(
            (
                "v3",
                scope.selection_mode,
                self._encode_digest(turn_digest),
                self._encode_digest(scope_digest),
                self._encode_digest(signature),
            )
        )

    def verify_scoped(
        self,
        turn: ConversationTurn,
        *,
        actor_id: UUID,
        configuration_version_id: UUID,
        scope: ConversationScopeBinding,
    ) -> bool:
        return (
            self.verify_scoped_status(
                turn,
                actor_id=actor_id,
                configuration_version_id=configuration_version_id,
                scope=scope,
            )
            is ScopedTurnVerification.VALID
        )

    def verify_scoped_status(
        self,
        turn: ConversationTurn,
        *,
        actor_id: UUID,
        configuration_version_id: UUID,
        scope: ConversationScopeBinding,
    ) -> ScopedTurnVerification:
        if (
            turn.role is not ConversationRole.ASSISTANT
            or turn.turn_id is None
            or turn.validation_token is None
        ):
            return ScopedTurnVerification.INVALID
        if not turn.validation_token.startswith("v3."):
            if scope.document_ids is not None:
                return ScopedTurnVerification.INVALID
            expected = self._sign_scoped_v2(
                content=turn.content,
                actor_id=actor_id,
                turn_id=turn.turn_id,
                configuration_version_id=configuration_version_id,
                scope=scope,
            )
            return (
                ScopedTurnVerification.VALID
                if hmac.compare_digest(turn.validation_token, expected)
                else ScopedTurnVerification.INVALID
            )

        parts = turn.validation_token.split(".")
        if len(parts) != 5:
            return ScopedTurnVerification.INVALID
        version, selection_mode, encoded_turn, encoded_scope, encoded_signature = parts
        if version != "v3" or selection_mode not in {
            "unrestricted",
            "selected_documents",
        }:
            return ScopedTurnVerification.INVALID
        try:
            turn_digest = self._decode_digest(encoded_turn)
            scope_digest = self._decode_digest(encoded_scope)
            signature = self._decode_digest(encoded_signature)
        except (ValueError, binascii.Error):
            return ScopedTurnVerification.INVALID
        if any(
            len(item) != hashlib.sha256().digest_size
            for item in (turn_digest, scope_digest, signature)
        ):
            return ScopedTurnVerification.INVALID
        envelope = self._scoped_envelope(
            selection_mode=selection_mode,
            turn_digest=turn_digest,
            scope_digest=scope_digest,
        )
        expected_signature = hmac.new(self.secret, envelope, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected_signature):
            return ScopedTurnVerification.INVALID

        expected_turn_digest = hashlib.sha256(
            self._message(
                content=turn.content,
                actor_id=actor_id,
                turn_id=turn.turn_id,
                configuration_version_id=configuration_version_id,
            )
        ).digest()
        if not hmac.compare_digest(turn_digest, expected_turn_digest):
            return ScopedTurnVerification.INVALID
        expected_scope_digest = hashlib.sha256(self._scope_message(scope)).digest()
        if selection_mode != scope.selection_mode or not hmac.compare_digest(
            scope_digest,
            expected_scope_digest,
        ):
            return ScopedTurnVerification.SCOPE_CHANGED
        return ScopedTurnVerification.VALID

    def _sign_scoped_v2(
        self,
        *,
        content: str,
        actor_id: UUID,
        turn_id: UUID,
        configuration_version_id: UUID,
        scope: ConversationScopeBinding,
    ) -> str:
        digest = hmac.new(
            self.secret,
            self._scoped_message_v2(
                content=content,
                actor_id=actor_id,
                turn_id=turn_id,
                configuration_version_id=configuration_version_id,
                scope=scope,
            ),
            hashlib.sha256,
        ).digest()
        return self._encode_digest(digest)

    @staticmethod
    def _message(
        *,
        content: str,
        actor_id: UUID,
        turn_id: UUID,
        configuration_version_id: UUID,
    ) -> bytes:
        content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return (
            f"v1\n{actor_id}\n{configuration_version_id}\n{turn_id}\n{content_digest}"
        ).encode("ascii")

    @staticmethod
    def _scoped_message_v2(
        *,
        content: str,
        actor_id: UUID,
        turn_id: UUID,
        configuration_version_id: UUID,
        scope: ConversationScopeBinding,
    ) -> bytes:
        content_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        workspaces = ",".join(str(item) for item in scope.normalized_workspace_ids)
        folders = ",".join(str(item) for item in scope.normalized_folder_ids)
        return (
            f"v2\n{actor_id}\n{configuration_version_id}\n{scope.domain_id}\n"
            f"{scope.connection_version_id}\n{workspaces}\n{folders}\n{turn_id}\n"
            f"{content_digest}"
        ).encode("ascii")

    @staticmethod
    def _scope_message(scope: ConversationScopeBinding) -> bytes:
        workspaces = ",".join(str(item) for item in scope.normalized_workspace_ids)
        folders = ",".join(str(item) for item in scope.normalized_folder_ids)
        documents = ",".join(
            str(item) for item in (scope.normalized_document_ids or ())
        )
        fingerprint = scope.scope_fingerprint or ""
        return (
            f"v3\n{scope.selection_mode}\n{scope.domain_id}\n"
            f"{scope.connection_version_id}\n{workspaces}\n{folders}\n"
            f"{documents}\n{fingerprint}"
        ).encode("ascii")

    @staticmethod
    def _scoped_envelope(
        *,
        selection_mode: str,
        turn_digest: bytes,
        scope_digest: bytes,
    ) -> bytes:
        return b"\n".join(
            (
                b"v3",
                selection_mode.encode("ascii"),
                turn_digest.hex().encode("ascii"),
                scope_digest.hex().encode("ascii"),
            )
        )

    @staticmethod
    def _encode_digest(digest: bytes) -> str:
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    @staticmethod
    def _decode_digest(encoded: str) -> bytes:
        padding = "=" * (-len(encoded) % 4)
        return base64.b64decode(
            encoded + padding,
            altchars=b"-_",
            validate=True,
        )
