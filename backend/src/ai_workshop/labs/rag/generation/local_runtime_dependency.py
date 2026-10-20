from typing import cast

from fastapi import Request

from ai_workshop.labs.rag.generation.local_model_host import LocalModelHost


def get_local_model_host(request: Request) -> LocalModelHost:
    """Share the application's model lifetime across request-scoped resolvers."""
    return cast(LocalModelHost, request.app.state.local_model_host)
