"""Same-state Haiku-skip debounce on the live Arena coach (BACKLOG.md:59).

Arena sibling of tests/test_aram_state_debounce.py. DEFAULT-OFF, fidelity-gated.
The coach relaxes POLL RATE on stable state but, pre-this-change, still paid a
Haiku `messages.create` every tick even when the coaching-relevant snapshot was
unchanged. This adds an opt-in coarse-state signature gate
(RC_ARENA_STATE_DEBOUNCE=1) that skips the redundant call and reuses the last
coaching dict, WITH a hard max-staleness ceiling so the coach can never go
truly stale.

These are BEHAVIORAL tests: they mock the Anthropic client and assert on the
Haiku call COUNT, not on source text. The coach is built via __new__ so we
skip the BaseCoach lifecycle (poll/vision loops, AppLoop, real SDK).

Cases:
  - OFF (default): N ticks -> N Haiku calls (byte-identical to today).
  - ON + identical signature within ceiling: N ticks -> 1 Haiku call; reused.
  - ON + identical signature but past ceiling: a second call fires.
  - ON + changed signature (round / item / HP band / next opponent): re-calls.
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

from coaches import arena_coach  # noqa: E402


# -- Fake Anthropic response/client -------------------------------------------

class _FakeUsage:
    input_tokens = 10
    output_tokens = 20
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeBlock:
    # A minimal valid Arena coach response so parse_fields succeeds.
    text = (
        "Action: ALL-IN\n"
        "Round strategy: trade then disengage at low HP\n"
        "Fight rule: burst when combo up\n"
        "Augment advice: take the prismatic offensive option\n"
        "Anvil advice: keep current\n"
        "Target priority: squishy carry first\n"
        "Risk: enemy displacement CC\n"
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


def _make_coach(tmp_out: Path) -> arena_coach.Coach:
    """Build a Coach WITHOUT BaseCoach.__init__ (no loops / SDK / AppLoop).

    Sets only the attributes _run_coach reads off self.
    """
    c = arena_coach.Coach.__new__(arena_coach.Coach)
    c._client = _FakeClient()
    c._out = tmp_out
    c._vision_state = {}
    c._api_key = "sk-ant-test"
    # _estimate_target_bonus_hp falls back to this when no enemy items are
    # visible; set it so the (caught) DS pre-call path stays clean.
    c._event_round_count = 0
    return c


def _state(hp: int = 90, level: int = 6, items=None, gold: int = 1200,
           round_: int = 3, kda: str = "3/1/4",
           next_opp: str = "Zed", next_opp_hp: int = 80) -> dict:
    return {
        "champion": "Yasuo",
        "game_mode": "CHERRY",
        "game_seconds": 600,
        "round": round_,
        "hp_pct": hp,
        "gold": gold,
        "level": level,
        "kda": kda,
        "rank": "1st",
        "alive_teams": 6,
        "wins": 1,
        "losses": 0,
        "items": items if items is not None else ["Berserker's Greaves"],
        "enemy_comp": [next_opp, "Lulu"],
        "augments": ["Blade Waltz"],
        "my_abilities": {},
        "summoner_d": "Flash",
        "summoner_f": "Flee",
        "teams": [
            {"name": "Yasuo", "hp_pct": hp, "is_you": True},
            {"name": "Partner", "hp_pct": 100, "is_partner": True},
            {"name": next_opp, "hp_pct": next_opp_hp, "is_next_opponent": True},
            {"name": "Lulu", "hp_pct": 100},
        ],
    }


class _DebounceTestBase(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "arena_coaching_data.json"
        # Seed a blank artifact so load_json has something to read.
        self.out.write_text(json.dumps({"mode": "arena"}), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _calls(self, coach: arena_coach.Coach) -> int:
        return coach._client.messages.calls


class StateDebounceOffTests(_DebounceTestBase):
    """DEFAULT-OFF: every tick calls Haiku (byte-identical to today)."""

    def test_off_n_ticks_n_calls(self) -> None:
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", False):
            c = _make_coach(self.out)
            st = _state()
            for _ in range(4):
                c._run_coach(st)
            self.assertEqual(self._calls(c), 4)

    def test_off_default_module_constant(self) -> None:
        # Sanity: the shipped default is OFF (env unset -> "0" -> False).
        # This pins the fidelity-gate: nothing flips it on implicitly.
        import os
        self.assertFalse(os.getenv("RC_ARENA_STATE_DEBOUNCE", "0") == "1")


class StateDebounceOnIdenticalTests(_DebounceTestBase):
    """ON + identical signature within ceiling: 1 call, rest reused."""

    def test_on_identical_signature_single_call(self) -> None:
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            st = _state()
            for _ in range(5):
                c._run_coach(st)
            self.assertEqual(self._calls(c), 1)

    def test_on_sub_bucket_jitter_does_not_bust_cache(self) -> None:
        # Intra-band jitter: HP 88 -> 82 (both decile band 8), gold 1200 ->
        # 1250 (both 300g band 4); next-opp HP held in-band (90 -> 80, both
        # 25% band 3). All collapse to one signature -> only tick 1 calls.
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(hp=88, gold=1200, next_opp_hp=90))
            jittered = _state(hp=82, gold=1250, next_opp_hp=80)
            c._run_coach(jittered)
            c._run_coach(jittered)
            self.assertEqual(self._calls(c), 1)

    def test_on_cached_coaching_reused_on_skip(self) -> None:
        # After the skip, the artifact still holds the first call's action.
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            st = _state()
            c._run_coach(st)
            after_first = json.loads(self.out.read_text(encoding="utf-8"))
            c._run_coach(st)  # skipped
            after_skip = json.loads(self.out.read_text(encoding="utf-8"))
            self.assertEqual(after_first.get("action"), "ALL-IN")
            self.assertEqual(after_skip.get("action"), "ALL-IN")
            self.assertEqual(self._calls(c), 1)


class StateDebounceCeilingTests(_DebounceTestBase):
    """ON + identical signature but past the max-staleness ceiling: re-calls."""

    def test_on_past_ceiling_second_call_fires(self) -> None:
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            st = _state()
            # First call records ts. Drive the clock forward past the ceiling
            # between calls so the unchanged signature still re-calls. A mutable
            # cell holds "now" so any number of time.time() reads per tick are
            # safe (no fixed-length iterator to exhaust).
            ceiling = arena_coach._STATE_DEBOUNCE_MAX_STALE_S
            now_cell = {"t": 1_000_000.0}
            with mock.patch("time.time", lambda: now_cell["t"]):
                c._run_coach(st)  # records ts = 1_000_000.0
                now_cell["t"] += ceiling + 1.0  # advance past ceiling
                c._run_coach(st)  # stale -> re-call despite identical sig
            self.assertEqual(self._calls(c), 2)


class StateDebounceChangedSigTests(_DebounceTestBase):
    """ON + changed signature: always calls."""

    def test_on_round_change_always_calls(self) -> None:
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(round_=3))
            c._run_coach(_state(round_=4))  # new round -> re-call
            self.assertEqual(self._calls(c), 2)

    def test_on_item_change_always_calls(self) -> None:
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(items=["Berserker's Greaves"]))
            c._run_coach(_state(items=["Berserker's Greaves", "Kraken Slayer"]))
            self.assertEqual(self._calls(c), 2)

    def test_on_big_hp_drop_crosses_band_and_calls(self) -> None:
        # HP 90 (band 9) -> 35 (band 3): a real mid-fight shift must re-call.
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(hp=90))
            c._run_coach(_state(hp=35))
            self.assertEqual(self._calls(c), 2)

    def test_on_next_opponent_change_always_calls(self) -> None:
        # Arena-specific: the matchup rotates each round. A new opponent is a
        # real tactical change and must always re-call even at the same HP/gold.
        with mock.patch.object(arena_coach, "_STATE_DEBOUNCE", True):
            c = _make_coach(self.out)
            c._run_coach(_state(next_opp="Zed"))
            c._run_coach(_state(next_opp="Garen"))
            self.assertEqual(self._calls(c), 2)


class SignatureUnitTests(unittest.TestCase):
    """Direct unit coverage of the coarse signature helper."""

    def test_jitter_same_signature(self) -> None:
        # Intra-band jitter (HP 88->82 band 8, gold 1200->1250 band 4,
        # next-opp HP 90->80 both 25% band 3) collapses to one signature.
        a = _coach_sig(_state(hp=88, gold=1200, next_opp_hp=90))
        b = _coach_sig(_state(hp=82, gold=1250, next_opp_hp=80))
        self.assertEqual(a, b)

    def test_round_crossing_differs(self) -> None:
        self.assertNotEqual(
            _coach_sig(_state(round_=3)), _coach_sig(_state(round_=4))
        )

    def test_next_opponent_in_signature(self) -> None:
        self.assertNotEqual(
            _coach_sig(_state(next_opp="Zed")),
            _coach_sig(_state(next_opp="Garen")),
        )

    def test_handles_none_and_empty(self) -> None:
        # Must not raise on degenerate input.
        self.assertIsInstance(
            arena_coach._coach_state_signature({}, {}), tuple
        )
        self.assertIsInstance(
            arena_coach._coach_state_signature(None, None), tuple
        )


def _coach_sig(state: dict) -> tuple:
    return arena_coach._coach_state_signature(state, {})


if __name__ == "__main__":
    unittest.main()
