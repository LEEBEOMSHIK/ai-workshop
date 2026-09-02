from unittest.mock import Mock

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
