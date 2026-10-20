"""The shared dependency must not relabel downstream failures as Codex failures."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from unittest.mock import sentinel

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.generation import codex_admin_api as module
from ai_workshop.main import create_app
from ai_workshop.shared.errors import AppError


@pytest.mark.parametrize(
    "error",
    [RuntimeError("synthetic downstream failure"), AppError("not_found", "Missing", 404),
     asyncio.CancelledError()],
)
async def test_downstream_error_identity_survives_dependency_cleanup(monkeypatch, error):
    closed = []

    @asynccontextmanager
    async def services(settings) -> AsyncIterator[object]:
        try:
            yield sentinel.services
        finally:
            closed.append(True)

    monkeypatch.setattr(module, "codex_services", services)
    dependency = module.get_codex_services(Settings(secret_key="x" * 32, _env_file=None))
    assert await anext(dependency) is sentinel.services
    with pytest.raises(type(error)) as caught:
        await dependency.athrow(error)
    assert caught.value is error
    assert closed == [True]


async def test_initialization_failure_retains_safe_codex_error(monkeypatch):
    @asynccontextmanager
    async def unavailable(settings) -> AsyncIterator[object]:
        raise RuntimeError("synthetic private diagnostic canary")
        yield  # pragma: no cover

    monkeypatch.setattr(module, "codex_services", unavailable)
    dependency = module.get_codex_services(Settings(secret_key="x" * 32, _env_file=None))
    with pytest.raises(AppError) as caught:
        await anext(dependency)
    assert caught.value.code == "codex_verification_unavailable"
    assert caught.value.status_code == 503
    assert "canary" not in caught.value.message


async def test_cleanup_failure_is_not_relabelled_as_initialization_failure(monkeypatch):
    error = RuntimeError("synthetic cleanup failure")

    @asynccontextmanager
    async def services(settings) -> AsyncIterator[object]:
        yield sentinel.services
        raise error

    monkeypatch.setattr(module, "codex_services", services)
    dependency = module.get_codex_services(Settings(secret_key="x" * 32, _env_file=None))
    await anext(dependency)
    with pytest.raises(RuntimeError) as caught:
        await anext(dependency)
    assert caught.value is error


@pytest.mark.parametrize("error", [AppError("not_found", "Missing", 404), asyncio.CancelledError()])
async def test_initialization_preserves_domain_error_and_cancellation(monkeypatch, error):
    @asynccontextmanager
    async def unavailable(settings) -> AsyncIterator[object]:
        raise error
        yield  # pragma: no cover

    monkeypatch.setattr(module, "codex_services", unavailable)
    dependency = module.get_codex_services(Settings(secret_key="x" * 32, _env_file=None))
    with pytest.raises(type(error)) as caught:
        await anext(dependency)
    assert caught.value is error


async def test_successful_request_closes_services_once(monkeypatch):
    closed = []

    @asynccontextmanager
    async def services(settings) -> AsyncIterator[object]:
        try:
            yield sentinel.services
        finally:
            closed.append(True)

    monkeypatch.setattr(module, "codex_services", services)
    dependency = module.get_codex_services(Settings(secret_key="x" * 32, _env_file=None))
    assert await anext(dependency) is sentinel.services
    with pytest.raises(StopAsyncIteration):
        await anext(dependency)
    assert closed == [True]


def test_downstream_failure_is_generic_http_500_without_private_detail(monkeypatch):
    closed = []

    @asynccontextmanager
    async def services(settings) -> AsyncIterator[object]:
        try:
            yield sentinel.services
        finally:
            closed.append(True)

    monkeypatch.setattr(module, "codex_services", services)
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        secret_key="x" * 32, _env_file=None
    )

    @app.get("/dependency-regression")
    async def fail(_services: Annotated[object, Depends(module.get_codex_services)]) -> None:
        raise RuntimeError("synthetic private diagnostic canary")

    # No lifespan: this transport regression never starts real services.
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.get("/dependency-regression")
    finally:
        client.close()
    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert "canary" not in response.text
    assert closed == [True]
