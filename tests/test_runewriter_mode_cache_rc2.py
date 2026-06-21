"""RC2 E12-L2 - RuneWriter lobby-mode memoization (port-safe).

RuneWriter._detect_game_mode() used to issue ONE unconditional
GET /lol-lobby/v2/lobby per poll tick (1.0s) for the lifetime of a
champ-select session, even though the lobby gameMode is immutable while
champ-select is open. E12-L2 memoizes the first successful read per session
so subsequent ticks serve the mode from cache - strictly FEWER LCU GETs, no
new poll loop, no faster cadence (port-safe).

The cache MUST invalidate on champ-select exit / champ change, which is the
exact contract of _reset_spell_state (the existing per-lock clear hook), so
the next session re-reads the live lobby.

Pure introspection with a fake LCU client - no live LCU, no sockets, no game.
"""
from __future__ import annotations

from lcu.lcu_rune_writer import RuneWriter


class _FakeLcu:
    """Minimal stand-in that counts GET /lol-lobby/v2/lobby calls."""

    def __init__(self, game_mode: str = "ARAM") -> None:
        self.game_mode = game_mode
        self.lobby_get_calls = 0

    def _request(self, method: str, path: str):
        if method == "GET" and path == "/lol-lobby/v2/lobby":
            self.lobby_get_calls += 1
            return {"gameConfig": {"gameMode": self.game_mode}}
        return None


def test_second_detect_served_from_cache_single_get():
    # (a) two consecutive _detect_game_mode calls with an unchanged lobby must
    # issue EXACTLY ONE GET /lol-lobby/v2/lobby - the 2nd is served from cache.
    fake = _FakeLcu("ARAM")
    rw = RuneWriter(fake)

    first = rw._detect_game_mode()
    assert fake.lobby_get_calls == 1

    second = rw._detect_game_mode()
    assert fake.lobby_get_calls == 1  # no extra GET - cache hit
    assert second == first == "ARAM"


def test_reset_spell_state_invalidates_cache():
    # (b) _reset_spell_state (champ-select exit / champ change) clears the
    # cache so the very next _detect_game_mode re-issues the GET.
    fake = _FakeLcu("CHERRY")
    rw = RuneWriter(fake)

    rw._detect_game_mode()
    assert fake.lobby_get_calls == 1

    rw._reset_spell_state()
    assert rw._cached_lobby_mode is None  # cache explicitly cleared

    rw._detect_game_mode()
    assert fake.lobby_get_calls == 2  # re-GET after invalidation


def test_cached_value_byte_identical_to_uncached():
    # (c) the cached mode value is byte-identical to a fresh uncached read.
    fake_uncached = _FakeLcu("KIWI")
    rw_uncached = RuneWriter(fake_uncached)
    uncached = rw_uncached._detect_game_mode()  # cold read

    fake_cached = _FakeLcu("KIWI")
    rw_cached = RuneWriter(fake_cached)
    rw_cached._detect_game_mode()               # priming read populates cache
    cached = rw_cached._detect_game_mode()       # cache hit

    assert cached == uncached
    assert cached is rw_cached._cached_lobby_mode


def test_cache_field_starts_none():
    # The per-session memo field is None before any detect call.
    rw = RuneWriter(_FakeLcu("ARAM"))
    assert rw._cached_lobby_mode is None
