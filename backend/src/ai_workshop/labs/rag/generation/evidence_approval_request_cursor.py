"""Signed cursors scoped to the actor, view, provider and revision filter."""

import base64
import binascii
import hmac
import json
from datetime import datetime
from uuid import UUID

from ai_workshop.config import Settings
from ai_workshop.shared.errors import AppError


class RequestCursor:
    def __init__(self, settings: Settings) -> None:
        self.maximum = settings.library_cursor_max_chars
        self.key = hmac.digest(
            settings.secret_key.get_secret_value().encode(),
            b"ai-workshop:evidence-request-cursor:v1",
            "sha256",
        )

    def encode(self, scope: list[str], created_at: datetime, id: UUID) -> str:
        raw = json.dumps([scope, created_at.isoformat(), str(id)], separators=(",", ":")).encode()
        result = base64.urlsafe_b64encode(raw + hmac.digest(self.key, raw, "sha256")).decode()
        if len(result) > self.maximum:
            raise AppError("evidence_request_cursor_unavailable", "Cursor limit is too small.", 503)
        return result

    def decode(self, token: str | None, scope: list[str]) -> tuple[datetime, UUID] | None:
        if token is None:
            return None
        try:
            if not token or len(token) > self.maximum:
                raise ValueError
            decoded = base64.b64decode(token, altchars=b"-_", validate=True)
            raw, signature = decoded[:-32], decoded[-32:]
            if not hmac.compare_digest(signature, hmac.digest(self.key, raw, "sha256")):
                raise ValueError
            value = json.loads(raw)
            if not isinstance(value, list) or len(value) != 3 or value[0] != scope:
                raise ValueError
            created_at, id = datetime.fromisoformat(value[1]), UUID(value[2])
            if created_at.tzinfo is None:
                raise ValueError
            return created_at, id
        except (ValueError, TypeError, binascii.Error, UnicodeError):
            raise AppError(
                "evidence_request_invalid_cursor", "Invalid request page cursor.", 422
            ) from None
