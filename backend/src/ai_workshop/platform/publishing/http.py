from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class NoStoreMiddleware:
    def __init__(self, app: ASGIApp, *, path_prefix: str = "") -> None:
        self.app = app
        self.path_prefix = path_prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        applies = scope["type"] == "http" and str(scope.get("path", "")).startswith(
            self.path_prefix
        )
        response_started = False

        async def send_no_store(message: Message) -> None:
            nonlocal response_started
            if applies and message["type"] == "http.response.start":
                response_started = True
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
            await send(message)

        if not applies:
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send_no_store)
        except Exception:
            if response_started:
                raise
            state = scope.get("state")
            correlation_id = (
                state.get("correlation_id", "unavailable")
                if isinstance(state, dict)
                else "unavailable"
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "internal_server_error",
                        "message": "The request could not be completed.",
                        "correlation_id": correlation_id,
                    }
                },
            )
            await response(scope, receive, send_no_store)
