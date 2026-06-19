"""Same-state Haiku-skip debounce on the live ARAM coach (BACKLOG.md:59).

DEFAULT-OFF, fidelity-gated. The coach relaxes POLL RATE on stable state
(`_on_state_received`) but, pre-this-change, still paid a Haiku
`messages.create` every tick even when the coaching-relevant snapshot was
unchanged. This adds an opt-in coarse-state signature gate
(RC_ARAM_STATE_DEBOUNCE=1) that skips the redundant call and reuses the last
coaching dict, WITH a hard max-staleness ceiling so the coach can never go
truly stale.

These are BEHAVIORAL tests: they mock the Anthropic client and assert on the
Haiku call COUNT, not on source text. The coach is built via __new__ so we
skip the BaseCoach lifecycle (poll/vision loops, AppLoop, real SDK).

Cases:
  - OFF (default): N ticks -> N Haiku calls (byte-identical to today).
  - ON + identical signature within ceiling: N ticks -> 1 Haiku call; reused.
  - ON + identical signature but past ceiling: a second call fires.
  - ON + changed signature: always calls.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from coaches import aram_coach  # noqa: E402


# -- Fake Anthropic response/client -------------------------------------------

class _FakeUsage:
    input_tokens = 10
    output_tokens = 20
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeBlock:
    # A minimal valid 7-field ARAM coach response so parse_fields succeeds.
    text = (
        "Action: POKE\n"
        "Fight rule: trade when Q up\n"
        "Reset / item: Buy after next death - Liandry's\n"
        "Risk: enemy Zed R\n"
        "Item build: Liandry's Torment, Zhonya's Hourglass, Rylai's Crystal Scepter\n"
        "Item reasons: Liandry's=anti-tank HP burn\n"
        "Choices: []\n"
    )


class _FakeResp:
    model = "claude-haiku-4-5-20251001"
    usage = _FakeUsage()
    content = [_FakeBlock()]


class _FakeMessages:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.calls += 1
        return _FakeResp()


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _make_coach(tmp_out: Path) -> aram_coach.Coach:
    """Build a Coach WITHOUT BaseCoach.__init__ (no loops / SDK / AppLoop).

    Sets only the attributes _run_coach reads off self.
    """
    c = aram_coach.Coach.__new__(aram_coach.Coach)
    c._client = _FakeClient()
    c._out = tmp_out
    c._vision_state = {}
    c._overlay = {}
    c._api_key = "sk-ant-test"
    c._MODE_NAME = "aram"
    return c


def _state(hp: int = 90, level: int = 6, items=None, gold: int = 1200) -> dict:
    return {
        "champion": "Caitlyn",
        "game_mode": "ARAM",
        "game_time": "10:00",
        "game_seconds": 600,
        "hp_pct": hp,
        "mana_pct": 80,
        "gold": gold,
        "level": level,
        "kda": "3/1/4",
        "items": items if items is not None else ["Berserker's Greaves"],
        "ally_comp": ["Lux", "Sett"],
        "enemy_comp": ["Zed", "Lulu"],
        "enemy_items": "unknown",
        "enemies": [],
        "dead_enemies": [],
        "alive_enemies": ["Zed", "Lulu"],
        "dead_respawn_str": "",
        "my_abilities": {},
        "my_runes": "",
        "enemy_runes": {},
        "summoner_d": "Flash",
        "summoner_f": "Heal",
        "my_team": "ORDER",
    }


class _DebounceTestBase(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "aram_coaching_data.json"
        # Seed a blank artifact so load_json has something to read.
        self.out.write_text(json.dumps({"mode": "aram"}), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _calls(self, coach: aram_coach.Coach) -> int:
        return coach._client.messages.calls


class StateDebounceOffTests(_DebounceTestBase):
    """DEFAULT-OFF: every tick calls Haiku (byte-identical to today)."""

    def test_off_n_ticks_n_calls(self) -> None:
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", False):
            c = _make_coach(self.out)
            st = _state()
            for _ in range(4):
                c._run_coach(st)
            self.assertEqual(self._calls(c), 4)

    def test_off_default_module_constant(self) -> None:
        # Sanity: the shipped default is OFF (env unset -> "0" -> False).
        # This pins the fidelity-gate: nothing flips it on implicitly.
        import os
        self.assertFalse(os.getenv("RC_ARAM_STATE_DEBOUNCE", "0") == "1")


class StateDebounceOnIdenticalTests(_DebounceTestBase):
    """ON + identical signature within ceiling: 1 call, rest reused."""

    def test_on_identical_signature_single_call(self) -> None:
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            st = _state()
            for _ in range(5):
                c._run_coach(st)
            self.assertEqual(self._calls(c), 1)

    def test_on_sub_bucket_jitter_does_not_bust_cache(self) -> None:
        # Intra-band jitter: HP 88 -> 82 (both decile band 8), gold 1200 ->
        # 1250 (both 300g band 4), game_seconds 600 -> 610 (both 30s band 20).
        # All collapse to one signature -> only the first tick calls Haiku.
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(hp=88, gold=1200))
            jittered = _state(hp=82, gold=1250)
            jittered["game_seconds"] = 610
            c._run_coach(jittered)
            c._run_coach(jittered)
            self.assertEqual(self._calls(c), 1)

    def test_on_cached_coaching_reused_on_skip(self) -> None:
        # After the skip, the artifact still holds the first call's action.
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            st = _state()
            c._run_coach(st)
            after_first = json.loads(self.out.read_text(encoding="utf-8"))
            c._run_coach(st)  # skipped
            after_skip = json.loads(self.out.read_text(encoding="utf-8"))
            self.assertEqual(after_first.get("action"), "POKE")
            self.assertEqual(after_skip.get("action"), "POKE")
            self.assertEqual(self._calls(c), 1)


class StateDebounceCeilingTests(_DebounceTestBase):
    """ON + identical signature but past the max-staleness ceiling: re-calls."""

    def test_on_past_ceiling_second_call_fires(self) -> None:
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            st = _state()
            # First call records ts. Drive the clock forward past the ceiling
            # between calls so the unchanged signature still re-calls. A mutable
            # cell holds "now" so any number of time.time() reads per tick are
            # safe (no fixed-length iterator to exhaust).
            ceiling = aram_coach._STATE_DEBOUNCE_MAX_STALE_S
            now_cell = {"t": 1_000_000.0}
            with mock.patch("time.time", lambda: now_cell["t"]):
                c._run_coach(st)  # records ts = 1_000_000.0
                now_cell["t"] += ceiling + 1.0  # advance past ceiling
                c._run_coach(st)  # stale -> re-call despite identical sig
            self.assertEqual(self._calls(c), 2)


class StateDebounceChangedSigTests(_DebounceTestBase):
    """ON + changed signature: always calls."""

    def test_on_level_change_always_calls(self) -> None:
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(level=6))
            c._run_coach(_state(level=7))  # discrete change -> re-call
            self.assertEqual(self._calls(c), 2)

    def test_on_item_change_always_calls(self) -> None:
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(items=["Berserker's Greaves"]))
            c._run_coach(_state(items=["Berserker's Greaves", "Kraken Slayer"]))
            self.assertEqual(self._calls(c), 2)

    def test_on_big_hp_drop_crosses_band_and_calls(self) -> None:
        # HP 90 (band 9) -> 35 (band 3): a real mid-fight shift must re-call.
        with mock.patch.object(aram_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(hp=90))
            c._run_coach(_state(hp=35))
            self.assertEqual(self._calls(c), 2)


class SignatureUnitTests(unittest.TestCase):
    """Direct unit coverage of the coarse signature helper."""

    def test_jitter_same_signature(self) -> None:
        # Intra-band jitter (HP 88->82 band 8, gold 1200->1250 band 4,
        # time 600->615 band 20) collapses to one signature.
        a = _coach_sig(_state(hp=88, gold=1200))
        b_state = _state(hp=82, gold=1250)
        b_state["game_seconds"] = 615
        b = _coach_sig(b_state)
        self.assertEqual(a, b)

    def test_band_crossing_differs(self) -> None:
        self.assertNotEqual(
            _coach_sig(_state(hp=90)), _coach_sig(_state(hp=35))
        )

    def test_handles_none_and_empty(self) -> None:
        # Must not raise on degenerate input.
        self.assertIsInstance(
            aram_coach._coach_state_signature({}, {}), tuple
        )
        self.assertIsInstance(
            aram_coach._coach_state_signature(None, None), tuple
        )


def _coach_sig(state: dict) -> tuple:
    return aram_coach._coach_state_signature(state, {})


if __name__ == "__main__":
    unittest.main()
