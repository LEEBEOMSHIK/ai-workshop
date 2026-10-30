"""Bound the imported JSON before FastAPI parses a request body, including chunked input."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute

from ai_workshop.labs.rag.comparisons.schemas import MAX_IMPORT_BYTES
from ai_workshop.shared.errors import AppError


class ComparisonRoute(APIRoute):
    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()

        async def bounded(request: Request) -> Response:
            if request.method == "POST":
                chunks: list[bytes] = []
                size = 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > MAX_IMPORT_BYTES:
                        raise AppError(
                            "comparison_too_large",
                            "The comparison file is too large.",
                            413,
                        )
                    chunks.append(chunk)
                # Starlette's body cache is required because stream() is single-consumption.
                request._body = b"".join(chunks)
            return await original(request)

        return bounded
