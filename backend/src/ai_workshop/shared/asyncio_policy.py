import asyncio
import sys


def configure_windows_selector_policy(*, platform: str | None = None) -> bool:
    if (platform or sys.platform) != "win32":
        return False
    policy_factory = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_factory is None:
        raise RuntimeError("The Windows selector event loop policy is unavailable.")
    asyncio.set_event_loop_policy(policy_factory())
    return True
