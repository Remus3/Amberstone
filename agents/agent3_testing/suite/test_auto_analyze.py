"""Round 15 - auto-analyze schedule + cancellation test."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.timeout(10)
def test_auto_analyze_schedules_then_cancels_on_game_start() -> None:
    """game->client schedules an analyzer run; a subsequent client->game
    cancels it before it fires."""
    from agents.supervisor import Supervisor

    sup = Supervisor()
    fake_analyze = MagicMock(return_value={"aram": {"champion_buckets": 1}})

    async def drive():
        # Shrink the idle wait so the test runs fast.
        with patch("agents.supervisor.IDLE_ANALYZE_SEC", 0.3), \
             patch("agents.agent4_coach_mentor.analyze_all", fake_analyze):
            # Fire game-end transition (under a running loop).
            sup._on_mode_transition("game", "client")
            await asyncio.sleep(0.05)    # let the task start
            assert sup._auto_analyze_task is not None
            assert not sup._auto_analyze_task.done()

            # Simulate a new game start before idle elapses.
            sup._on_mode_transition("client", "game")
            await asyncio.sleep(0.05)
            # Task should be cancelled.
            assert sup._auto_analyze_task.cancelled() or sup._auto_analyze_task.done()
            fake_analyze.assert_not_called()
    asyncio.run(drive())


@pytest.mark.timeout(10)
def test_auto_analyze_fires_after_idle() -> None:
    from agents.supervisor import Supervisor

    sup = Supervisor()
    fake_analyze = MagicMock(return_value={"aram": {"champion_buckets": 42}})

    async def drive():
        with patch("agents.supervisor.IDLE_ANALYZE_SEC", 0.2), \
             patch("agents.agent4_coach_mentor.analyze_all", fake_analyze):
            sup._on_mode_transition("game", "client")
            # Wait past the idle window.
            await asyncio.sleep(0.5)
            fake_analyze.assert_called_once()
    asyncio.run(drive())


@pytest.mark.timeout(10)
def test_game_to_game_transition_does_not_cancel_nothing() -> None:
    """Sanity - transitioning game->in_progress (an intra-game label
    change) mustn't error just because there's no pending task."""
    from agents.supervisor import Supervisor

    sup = Supervisor()
    assert sup._auto_analyze_task is None
    # Directly call the cancel path - exercises the "no pending" branch.
    sup._cancel_pending_auto_analyze("test")    # no raise
    # And call _on_mode_transition from a running loop so the
    # loop.call_soon_threadsafe path doesn't error.
    async def drive():
        sup._on_mode_transition("in_progress", "game")    # still in-game
    asyncio.run(drive())
