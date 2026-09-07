"""Cross-seam no-flap guard for body[data-mode] during lobby preflip.

Bug (2026-05-17, fixed in cef09d31): in an ARAM/Arena lobby or champ
select the dashboard had two disagreeing mode authorities writing
``body[data-mode]`` on independent cadences:

  - onState - the HTTP /api/state envelope, whose ``mode_key`` is the
    canonical resolver (dashboard._state_builder.build_state preflips it
    from the LCU lobby/champ-select queue_id).
  - onHealth - a health envelope whose tag is derived *purely* from the
    per-mode flags (``aram_mode`` / ``arena_mode`` / ``brawl_mode`` /
    ``tft_mode``); absent any flag it falls back to "client"
    (web/js/main.js onHealth, lines ~1493-1496).

It flapped aram<->client ~1x/sec and every mode-gated header pill
flickered. The server-side correctness fix mirrors the active preflip
into the per-mode health flag on *both* health-broadcast seams so the
two authorities resolve the same tag:

  - the HTTP seam: build_state stamps out["health"][f"{mode}_mode"]
    (pinned by test_state_builder_preflip.TestBuildStatePreflipFlagMirror)
  - the WS seam: agent2_backend.file_ingest._check_one mirrors the LCU
    preflip into the broadcast health envelope
    (pinned by test_file_ingest_mirror.FileIngestMirrorTests)

Those two suites each verify one seam half in isolation. This suite
pins the *invariant that ties them together*: driven from the SAME LCU
lobby snapshot, the onHealth tag derived from the HTTP-seam health flags
and the onHealth tag derived from the WS-seam health flags must be
identical AND equal to build_state's onState mode_key. When all three
agree there is no source of disagreement left to flap body[data-mode].

(The residual /api/health raw-poll path is deliberately NOT mirrored
server-side and is covered by the client-side deferral backstop in
test_mode_flap_deferral_dom; it is out of scope for this seam guard.)
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agents.agent2_backend import file_ingest
from agents.agent2_backend.file_ingest import FileIngest
from dashboard import _state_builder
from tests._asyncio_isolation import run_coro as _run_coro


# --- onHealth tag derivation, mirrored from web/js/main.js:1493-1496 ------
def _derive_health_tag(payload: dict) -> str:
    """Pure port of the dashboard onHealth flag->tag resolution.

    If this drifts from main.js the test loses its meaning, so the order
    and flag names are pinned 1:1 with the JS."""
    if payload.get("aram_mode"):
        return "aram"
    if payload.get("arena_mode"):
        return "arena"
    if payload.get("brawl_mode"):
        return "brawl"
    if payload.get("tft_mode"):
        return "tft"
    return "client"


def _empty_health() -> dict:
    return {"alive": True, "pid": 1, "mode": "client",
            "has_game": False, "ui_pulse_age_s": 0.1,
            "game_poll_worker_age_s": 0.1,
            "aram_mode": False, "arena_mode": False, "tft_mode": False}


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def broadcast_push(self, env: dict) -> None:
        self.sent.append(env)


# Each scenario: a single LCU snapshot fed to BOTH seams, plus the mode
# both must agree on. "client" means no preflip (flags stay dark).
_SCENARIOS = [
    ("aram_mayhem_lobby",
     {"phase": "Lobby", "lobby": {"queue_id": 2400, "is_custom": False}},
     "aram"),
    ("aram_normal_lobby",
     {"phase": "Lobby", "lobby": {"queue_id": 450, "is_custom": False}},
     "aram"),
    ("arena_lobby",
     {"phase": "Lobby", "lobby": {"queue_id": 1700, "is_custom": False}},
     "arena"),
    ("aram_champ_select",
     {"phase": "ChampSelect", "champ_select": {"queue_id": 2400}},
     "aram"),
    ("no_lobby_stays_client",
     {"phase": "None"},
     "client"),
    ("custom_lobby_stays_client",
     {"phase": "Lobby", "lobby": {"queue_id": 2400, "is_custom": True}},
     "client"),
]


class BodyDataModeNoFlapTests(unittest.TestCase):
    """For each LCU snapshot, the HTTP-seam tag, the WS-seam tag, and the
    onState mode_key must all agree - the precondition for a stable
    body[data-mode].

    PLAIN TestCase, NOT IsolatedAsyncioTestCase - see the sibling note in
    test_file_ingest_mirror.py. IsolatedAsyncioTestCase enters the loop via
    `asyncio.Runner.run()` on the MAIN thread, which raises whenever
    Playwright has left its running-loop marker set there, so this test was
    green alone and red in any run that also collected snapshot_panels. The
    WS-seam coroutine now goes through run_coro; the assertions and the
    scenario matrix are unchanged.
    """

    def setUp(self) -> None:
        self._patches = [
            mock.patch.object(_state_builder, "validate_coaching_payload",
                              lambda x: None),
            mock.patch.object(_state_builder, "liveclient_summary",
                              return_value={}),
            mock.patch.object(_state_builder, "get_team_context",
                              return_value=None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()

    def _http_seam_tag(self, lcu: dict) -> tuple[str, str]:
        """Run the onState/HTTP authority. Returns (mode_key, onHealth tag
        derived from the mirrored out['health'] flags)."""
        def _read_json(path: str) -> dict:
            if path.endswith("health.json"):
                return _empty_health()
            return {}

        with mock.patch.object(_state_builder, "read_json",
                               side_effect=_read_json), \
             mock.patch.object(_state_builder, "lcu_summary",
                               return_value=lcu):
            out = _state_builder.build_state()
        return out["mode_key"], _derive_health_tag(out["health"])

    async def _ws_seam_tag(self, lcu: dict) -> str:
        """Run the onHealth/WS authority (file_ingest broadcast). Returns
        the onHealth tag derived from the broadcast health flags."""
        ws = _FakeWS()
        fi = FileIngest(ws)
        with TemporaryDirectory() as d:
            hp = Path(d) / "health.json"
            hp.write_text(json.dumps(_empty_health()), encoding="utf-8")
            with mock.patch.object(file_ingest, "_lcu_summary",
                                   return_value=lcu):
                await fi._check_one(hp, "health", mode="any",
                                    envelope_type="health")
        self.assertEqual(len(ws.sent), 1, "expected one health broadcast")
        return _derive_health_tag(ws.sent[0]["payload"])

    def test_seams_agree_no_flap(self) -> None:
        for name, lcu, expected in _SCENARIOS:
            with self.subTest(scenario=name):
                mode_key, http_tag = self._http_seam_tag(lcu)
                ws_tag = _run_coro(self._ws_seam_tag(lcu))
                # onState authority resolves the expected mode.
                self.assertEqual(
                    mode_key, expected,
                    f"{name}: build_state mode_key drifted")
                # The HTTP-seam health flags resolve to the SAME tag, so
                # onState and the mirrored onHealth never disagree.
                self.assertEqual(
                    http_tag, expected,
                    f"{name}: HTTP-seam health flag tag disagrees with "
                    f"mode_key - body[data-mode] would flap")
                # The WS-seam broadcast resolves to the SAME tag too.
                self.assertEqual(
                    ws_tag, expected,
                    f"{name}: WS-seam broadcast tag disagrees - "
                    f"body[data-mode] would flap")
                # Explicit three-way agreement (the no-flap invariant).
                self.assertEqual(
                    {mode_key, http_tag, ws_tag}, {expected},
                    f"{name}: the three mode authorities disagree")


if __name__ == "__main__":
    unittest.main()
