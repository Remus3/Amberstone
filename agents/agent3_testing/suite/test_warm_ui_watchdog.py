"""Unit tests for the warm-session UI-close watchdog (supervisor-level).

We don't boot a real supervisor — we exercise the loop body directly
with a mocked ws server + warm session. A fake monotonic clock lets us
fast-forward past the grace window.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _run(coro):
    return asyncio.run(coro)


class _FakeWarm:
    def __init__(self, warm: bool = True) -> None:
        self._warm = warm
        self.closed = False

    def stats(self) -> dict:
        return {"warm": self._warm}

    def close(self) -> None:
        self.closed = True
        self._warm = False


@pytest.mark.timeout(10)
def test_watchdog_closes_warm_after_grace() -> None:
    from agents.supervisor import Supervisor

    sup = Supervisor()
    ws = SimpleNamespace(push_subscribers=0)
    warm = _FakeWarm(warm=True)
    sup._ws = ws                    # type: ignore[assignment]
    sup._warm_agent7 = warm         # type: ignore[assignment]

    async def drive():
        # Shrink real intervals so the test runs in well under a second.
        with patch("agents.supervisor.WARM_UI_CHECK_INTERVAL_SEC", 0.02), \
             patch("agents.supervisor.WARM_UI_CLOSE_GRACE_SEC", 0.1):
            task = asyncio.create_task(sup._warm_ui_watchdog())
            # Wait well beyond grace + 1 check interval.
            await asyncio.sleep(0.35)
            sup._stop.set()
            await task
    _run(drive())
    assert warm.closed is True


@pytest.mark.timeout(10)
def test_watchdog_resets_on_subscriber_reconnect() -> None:
    """If UI reconnects within grace window, warm survives."""
    from agents.supervisor import Supervisor

    sup = Supervisor()
    ws = SimpleNamespace(push_subscribers=0)
    warm = _FakeWarm(warm=True)
    sup._ws = ws                    # type: ignore[assignment]
    sup._warm_agent7 = warm         # type: ignore[assignment]

    async def drive():
        with patch("agents.supervisor.WARM_UI_CHECK_INTERVAL_SEC", 0.02), \
             patch("agents.supervisor.WARM_UI_CLOSE_GRACE_SEC", 0.5):
            task = asyncio.create_task(sup._warm_ui_watchdog())
            await asyncio.sleep(0.05)    # zero_since armed
            ws.push_subscribers = 2      # UI reconnected
            await asyncio.sleep(0.05)    # watchdog should reset
            ws.push_subscribers = 0      # UI gone again
            await asyncio.sleep(0.05)    # new zero_since
            # Total elapsed < 0.5s, so warm must still be open.
            assert not warm.closed
            sup._stop.set()
            await task
    _run(drive())


@pytest.mark.timeout(10)
def test_watchdog_noop_when_not_warm() -> None:
    from agents.supervisor import Supervisor

    sup = Supervisor()
    sup._ws = SimpleNamespace(push_subscribers=0)     # type: ignore
    sup._warm_agent7 = _FakeWarm(warm=False)           # type: ignore

    async def drive():
        with patch("agents.supervisor.WARM_UI_CHECK_INTERVAL_SEC", 0.01), \
             patch("agents.supervisor.WARM_UI_CLOSE_GRACE_SEC", 0.05):
            task = asyncio.create_task(sup._warm_ui_watchdog())
            await asyncio.sleep(0.2)
            sup._stop.set()
            await task
    _run(drive())
    assert sup._warm_agent7.closed is False


@pytest.mark.timeout(10)
def test_watchdog_handles_missing_ws_gracefully() -> None:
    from agents.supervisor import Supervisor

    sup = Supervisor()
    # _ws is None — watchdog must not crash.

    async def drive():
        with patch("agents.supervisor.WARM_UI_CHECK_INTERVAL_SEC", 0.01):
            task = asyncio.create_task(sup._warm_ui_watchdog())
            await asyncio.sleep(0.05)
            sup._stop.set()
            await task
    _run(drive())
