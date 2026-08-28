from contextvars import ContextVar, Token
from uuid import UUID, uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CORRELATION_ID_HEADER = "x-correlation-id"
correlation_id_context: ContextVar[str] = ContextVar(
    "correlation_id",
    default="unavailable",
)


def _valid_or_new_correlation_id(value: str | None) -> str:
    if value is None:
        return str(uuid4())
    try:
        return str(UUID(value))
    except ValueError:
        return str(uuid4())


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        incoming = headers.get(CORRELATION_ID_HEADER.encode("latin-1"))
        correlation_id = _valid_or_new_correlation_id(
            incoming.decode("latin-1") if incoming else None
        )
        scope.setdefault("state", {})["correlation_id"] = correlation_id
        token: Token[str] = correlation_id_context.set(correlation_id)

        async def send_with_correlation_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append(
                    (
                        CORRELATION_ID_HEADER.encode("latin-1"),
                        correlation_id.encode("latin-1"),
                    )
                )
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_correlation_id)
        finally:
            correlation_id_context.reset(token)
