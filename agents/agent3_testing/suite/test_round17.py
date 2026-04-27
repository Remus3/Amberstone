"""Round 17 — champ-select warm-prime coverage."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest


class _FakeWarm:
    def __init__(self, warm: bool = False) -> None:
        self._warm = warm
        self.sends: list[str] = []

    def stats(self) -> dict:
        return {"warm": self._warm}

    def send(self, text: str, max_tokens: int = 0) -> dict:
        self.sends.append(text)
        self._warm = True
        return {"text": "READY", "model": "claude-haiku-4-5", "turns": 1,
                "input_tokens": 5, "output_tokens": 2}

    def close(self) -> None:
        self._warm = False


@pytest.mark.timeout(5)
def test_champ_select_primes_warm() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    warm = _FakeWarm(warm=False)
    sup._warm_agent7 = warm       # type: ignore[assignment]

    async def drive():
        sup._on_mode_transition("client", "champ_select")
    asyncio.run(drive())

    assert len(warm.sends) == 1
    assert "champ-select" in warm.sends[0].lower()


@pytest.mark.timeout(5)
def test_champ_select_skips_prime_if_already_warm() -> None:
    from agents.supervisor import Supervisor
    sup = Supervisor()
    warm = _FakeWarm(warm=True)
    sup._warm_agent7 = warm

    async def drive():
        sup._on_mode_transition("client", "pregame")
    asyncio.run(drive())
    assert warm.sends == []


@pytest.mark.timeout(5)
def test_game_end_from_champ_select_does_not_prime_again() -> None:
    """champ_select → client transition should NOT prime (we prime on
    entry to champ_select, not exit)."""
    from agents.supervisor import Supervisor
    sup = Supervisor()
    warm = _FakeWarm(warm=False)
    sup._warm_agent7 = warm

    async def drive():
        sup._on_mode_transition("champ_select", "client")
    asyncio.run(drive())
    assert warm.sends == []


@pytest.mark.timeout(5)
def test_game_start_still_primes_after_champ_select() -> None:
    """champ_select → game should trigger game-start prime path, not
    champ-select path."""
    from agents.supervisor import Supervisor
    sup = Supervisor()
    warm = _FakeWarm(warm=False)
    sup._warm_agent7 = warm

    async def drive():
        sup._on_mode_transition("champ_select", "game")
    asyncio.run(drive())
    assert len(warm.sends) == 1
    assert "game" in warm.sends[0].lower()
