import asyncio
import sys
from unittest.mock import Mock

import pytest
from uvicorn import Config

import ai_workshop.shared.asyncio_policy as policy_module
from ai_workshop.shared.asyncio_policy import configure_windows_selector_policy


def test_windows_worker_selects_a_psycopg_compatible_event_loop(monkeypatch) -> None:
    expected_policy = object()
    factory = Mock(return_value=expected_policy)
    setter = Mock()
    monkeypatch.setattr(
        policy_module.asyncio,
        "WindowsSelectorEventLoopPolicy",
        factory,
        raising=False,
    )
    monkeypatch.setattr(policy_module.asyncio, "set_event_loop_policy", setter)

    assert configure_windows_selector_policy(platform="win32") is True
    setter.assert_called_once_with(expected_policy)


def test_non_windows_worker_keeps_the_runtime_default(monkeypatch) -> None:
    setter = Mock()
    monkeypatch.setattr(policy_module.asyncio, "set_event_loop_policy", setter)

    assert configure_windows_selector_policy(platform="linux") is False
    setter.assert_not_called()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows API loop regression")
def test_uvicorn_api_runs_selector_even_without_reload() -> None:
    original_policy = asyncio.get_event_loop_policy()
    try:
        configure_windows_selector_policy()
        config = Config(
            "unused:app",
            loop="ai_workshop.shared.asyncio_policy:create_selector_event_loop",
            reload=False,
            log_config=None,
        )

        async def running_loop() -> asyncio.AbstractEventLoop:
            return asyncio.get_running_loop()

        with asyncio.Runner(loop_factory=config.get_loop_factory()) as runner:
            assert isinstance(runner.run(running_loop()), asyncio.SelectorEventLoop)
    finally:
        asyncio.set_event_loop_policy(original_policy)


@pytest.mark.parametrize("reload", [False, True])
def test_explicit_uvicorn_factory_is_fresh_and_does_not_change_process_policy(reload) -> None:
    original_policy = asyncio.get_event_loop_policy()
    config = Config(
        "unused:app",
        loop="ai_workshop.shared.asyncio_policy:create_selector_event_loop",
        reload=reload,
        log_config=None,
    )
    factory = config.get_loop_factory()
    assert factory is not None
    first, second = factory(), factory()
    try:
        assert isinstance(first, asyncio.SelectorEventLoop)
        assert isinstance(second, asyncio.SelectorEventLoop)
        assert first is not second
        assert not first.is_closed() and not second.is_closed()
        assert asyncio.get_event_loop_policy() is original_policy
    finally:
        first.close()
        second.close()
