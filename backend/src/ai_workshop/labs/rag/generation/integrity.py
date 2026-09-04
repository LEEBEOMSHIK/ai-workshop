import base64
import hashlib
import hmac
from uuid import UUID

from ai_workshop.labs.rag.generation.domain import ConversationRole, ConversationTurn


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
