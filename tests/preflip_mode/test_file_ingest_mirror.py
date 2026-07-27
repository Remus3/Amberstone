"""Regression guard for the WS /push health preflip mirror.

The :8891 file_ingest path (agents/agent2_backend/file_ingest.py
_check_one) must mirror the s150 LCU lobby/champ-select pre-flip into
the health envelope it broadcasts, so the dashboard's onHealth tag
resolution agrees with onState's /api/state mode_key. When it doesn't,
body[data-mode] flaps aram<->client and every mode-gated header pill
flickers (the 2026-05-17 bug; the client-side deferral in main.js is
the defensive backstop, this is the server-side correctness path).

The live failure that motivated this test was a *deployment* problem
(the long-running supervisor process predated the keystone 3eb2e2d
commit that taught queue_modes about queue 2400, so its imported code
couldn't resolve the ARAM Mayhem lobby) - a restart fixed that. These
tests instead pin the *logic* wiring so a future refactor of
_check_one that drops/breaks the mirror call is caught in CI:

  - _PREFLIP_AVAILABLE must be True (the dashboard import from the
    agents context is load-bearing - a False silently disables the
    whole feature)
  - an ARAM/Arena lobby snapshot must produce a mirrored health
    envelope (aram_mode/arena_mode flipped True)
  - no recognised lobby/CS must NOT spuriously mirror
  - state (non-health) envelopes are never mirrored
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agents.agent2_backend import file_ingest
from agents.agent2_backend.file_ingest import FileIngest, _PREFLIP_AVAILABLE
from tests._asyncio_isolation import run_coro as _run_coro


class _FakeWS:
    """Captures broadcast_push envelopes."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def broadcast_push(self, env: dict) -> None:
        self.sent.append(env)


_RAW_HEALTH = {
    "mode": "client",
    "has_game": False,
    "aram_mode": False,
    "arena_mode": False,
    "tft_mode": False,
    "pid": 1234,
    "alive": True,
    "last_reload_ok": True,
}


class PreflipAvailableTests(unittest.TestCase):
    def test_dashboard_import_succeeds_from_agents_context(self) -> None:
        # The whole mirror feature is gated on this import working when
        # file_ingest is loaded by `python -m agents.supervisor`. A
        # False here means the supervisor silently broadcasts raw health.
        self.assertTrue(
            _PREFLIP_AVAILABLE,
            "dashboard._liveclient / dashboard._state_builder failed to "
            "import from the agents context - the WS health mirror is "
            "silently disabled",
        )


class FileIngestMirrorTests(unittest.TestCase):
    """Drive _check_one with a temp health.json + a patched _lcu_summary
    and assert the broadcast health envelope is preflip-mirrored.

    PLAIN TestCase, NOT IsolatedAsyncioTestCase, and that is load-bearing.
    IsolatedAsyncioTestCase drives asyncSetUp through `asyncio.Runner.run()`
    on the MAIN thread, and Playwright's sync API leaves asyncio's
    running-loop marker set on that thread for the whole session
    (tests/_asyncio_isolation.py documents the measurement). So every test in
    this class raised "Runner.run() cannot be called from a running event
    loop" whenever it sorted after a snapshot_panels test in the same
    process - green alone, red in the nightly dual suite, and red under
    `-n 8` when a worker happened to draw both files.

    The coroutines therefore run through `run_coro`, which drives them on a
    fresh loop in a dedicated thread; a fresh thread has no running-loop
    marker, so it is immune. Assertions are unchanged.
    """

    def _write_health(self, tmp: Path) -> Path:
        p = tmp / "health.json"
        p.write_text(json.dumps(_RAW_HEALTH), encoding="utf-8")
        return p

    async def _broadcast_health(self, lcu_snapshot) -> dict:
        ws = _FakeWS()
        fi = FileIngest(ws)
        with TemporaryDirectory() as d:
            hp = self._write_health(Path(d))
            with mock.patch.object(
                file_ingest, "_lcu_summary", return_value=lcu_snapshot
            ):
                await fi._check_one(
                    hp, "health", mode="any", envelope_type="health"
                )
        self.assertEqual(len(ws.sent), 1, "expected exactly one broadcast")
        env = ws.sent[0]
        self.assertEqual(env["type"], "health")
        return env["payload"]

    def test_aram_mayhem_lobby_mirrors_aram_mode(self) -> None:
        # queue 2400 = ARAM Mayhem (KIWI) - the exact live repro.
        payload = _run_coro(self._broadcast_health(
            {"phase": "Lobby", "lobby": {"queue_id": 2400, "is_custom": False}}
        ))
        self.assertIs(
            payload["aram_mode"], True,
            "ARAM Mayhem lobby must mirror aram_mode=True into the health "
            "envelope",
        )
        # The mirror only sets the flag; mode string stays as-is (onHealth
        # checks aram_mode before falling back to .mode).
        self.assertEqual(payload["mode"], "client")

    def test_arena_lobby_mirrors_arena_mode(self) -> None:
        payload = _run_coro(self._broadcast_health(
            {"phase": "Lobby", "lobby": {"queue_id": 1700, "is_custom": False}}
        ))
        self.assertIs(payload["arena_mode"], True)

    def test_champ_select_queue_mirrors(self) -> None:
        payload = _run_coro(self._broadcast_health(
            {"phase": "ChampSelect", "champ_select": {"queue_id": 2400}}
        ))
        self.assertIs(payload["aram_mode"], True)

    def test_no_lobby_does_not_spuriously_mirror(self) -> None:
        payload = _run_coro(self._broadcast_health({"phase": "None"}))
        self.assertIs(payload["aram_mode"], False)
        self.assertIs(payload["arena_mode"], False)
        self.assertEqual(payload["mode"], "client")

    def test_custom_lobby_does_not_mirror(self) -> None:
        payload = _run_coro(self._broadcast_health(
            {"phase": "Lobby", "lobby": {"queue_id": 2400, "is_custom": True}}
        ))
        self.assertIs(payload["aram_mode"], False)

    def test_state_envelope_is_never_mirrored(self) -> None:
        # Only health envelopes carry the mirror; a state envelope must
        # pass through untouched even if an ARAM lobby is active.
        #
        # The await lives in a nested coroutine driven by _run_coro rather
        # than in an `async def test_`: on a plain TestCase pytest would not
        # await an async test at all - it would emit "coroutine was never
        # awaited" and PASS without executing a single assertion, which is a
        # worse outcome than the RuntimeError this conversion fixes.
        ws = _FakeWS()
        fi = FileIngest(ws)

        async def _drive(state_path: Path) -> None:
            with mock.patch.object(
                file_ingest, "_lcu_summary",
                return_value={"phase": "Lobby",
                              "lobby": {"queue_id": 2400, "is_custom": False}},
            ):
                await fi._check_one(
                    state_path, "aram_coaching_data.json", mode="aram",
                    envelope_type="state",
                )

        with TemporaryDirectory() as d:
            sp = Path(d) / "aram_coaching_data.json"
            sp.write_text(json.dumps({"action": "x"}), encoding="utf-8")
            _run_coro(_drive(sp))
        self.assertEqual(len(ws.sent), 1)
        self.assertEqual(ws.sent[0]["type"], "state")
        self.assertNotIn("aram_mode", ws.sent[0]["payload"])


if __name__ == "__main__":
    unittest.main()
