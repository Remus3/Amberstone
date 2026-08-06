"""No test may write the production cost ledger at `data/spend/`.

Root cause (S5, 2026-08-06). `tests/test_aram_state_debounce.py` and
`tests/test_arena_state_debounce.py` drive the REAL ARAM / Arena coaches
through `Coach._run_coach` with a mocked Anthropic client whose response
carries `_FakeUsage(input_tokens=10, output_tokens=20)`. That reaches
`coaches/_base_coach.py:713 _record_coach_call`, which calls
`core.cost_tracker.get_tracker().record_call(...)` - and `get_tracker()`
is the process singleton bound to the module-global `_SPEND_DIR`, i.e. the
operator's real financial telemetry. Their `setUp` tempdir-isolates only
the coaching-data artifact, so every suite run booked synthetic spend into
`data/spend/<today>.json`.

The ceiling test in each file also patches `time.time`, and `date.today()`
reads the clock through it, so one run additionally minted a
`data/spend/1970-01-12.json` - epoch + 1_000_000s, the patched value. That
phantom day-file is the fingerprint proving the leak, not inferring it.

This file pins the fix in two independent ways so neither can pass
vacuously:

  * `TrackerRedirectInForceTests` asserts the autouse conftest fixture
    actually re-pointed the tracker (mirrors the
    `tests/test_no_live_ocr_thread_in_suite.py` precedent - a hermeticity
    net nobody asserts is a net that silently stops being installed).
  * `CoachCallContainmentTests` drives the real ARAM coach exactly the way
    the debounce suite does and asserts BOTH that the call was recorded
    (so the harness provably reached `record_call`) AND that the production
    ledger is byte-unchanged. Asserting only the second half would pass on
    a harness that broke before the model call - which is exactly how
    `tests/test_coach_ds_inventory_filter.py` avoids the leak by accident.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core import cost_tracker as ct  # noqa: E402


def _production_spend_dir() -> Path:
    """The real ledger dir, resolved off the MODULE not off `_SPEND_DIR`.

    `_SPEND_DIR` is what the autouse fixture monkeypatches, so reading it
    here would make every assertion below tautological.
    """
    return Path(ct.__file__).resolve().parent.parent / "data" / "spend"


def _snapshot(d: Path) -> dict:
    if not d.is_dir():
        return {}
    return {p.name: p.stat().st_size for p in d.iterdir() if p.is_file()}


# -- Fake Anthropic response (deliberately NOT 10/20) -------------------------
# Distinct token counts so a leaked row is attributable to THIS file rather
# than to the debounce suite it is guarding.

class _FakeUsage:
    input_tokens = 7
    output_tokens = 13
    cache_read_input_tokens = 0
    cache_creation_input_tokens = 0


class _FakeBlock:
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


def _state() -> dict:
    return {
        "champion": "Caitlyn",
        "game_mode": "ARAM",
        "game_time": "10:00",
        "game_seconds": 600,
        "hp_pct": 90,
        "mana_pct": 80,
        "gold": 1200,
        "level": 6,
        "kda": "3/1/4",
        "items": ["Berserker's Greaves"],
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


class TrackerRedirectInForceTests(unittest.TestCase):
    """The autouse redirect must be installed for every test in this suite."""

    def test_module_spend_dir_is_not_production(self) -> None:
        prod = _production_spend_dir()
        self.assertNotEqual(
            Path(ct._SPEND_DIR).resolve(), prod,
            "core.cost_tracker._SPEND_DIR still points at the production "
            "ledger during a test run - the autouse hermeticity fixture in "
            "tests/conftest.py is not in force",
        )

    def test_singleton_tracker_writes_outside_production(self) -> None:
        prod = _production_spend_dir()
        tracker_dir = Path(ct.get_tracker()._spend_dir).resolve()
        self.assertNotEqual(
            tracker_dir, prod,
            "get_tracker() handed back a tracker bound to the production "
            "ledger - the fixture redirected _SPEND_DIR but failed to reset "
            "the module singleton",
        )

    def test_recorded_call_lands_in_the_redirected_dir(self) -> None:
        tracker = ct.get_tracker()
        tracker.record_call(
            model="claude-haiku-4-5-20251001",
            input_tokens=7, output_tokens=13, purpose="aram_coach",
        )
        landed = Path(tracker._spend_dir) / (date.today().isoformat() + ".json")
        self.assertTrue(
            landed.is_file(),
            "record_call wrote nothing where the redirect points, so the "
            "assertions above prove containment of a write that never "
            "happened",
        )
        doc = json.loads(landed.read_text(encoding="utf-8"))
        self.assertGreaterEqual(doc.get("calls", 0), 1)


class CoachCallContainmentTests(unittest.TestCase):
    """The real coach path must not reach the production ledger."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.out = Path(self._tmpdir.name) / "aram_coaching_data.json"
        self.out.write_text(json.dumps({"mode": "aram"}), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _make_coach(self):
        from coaches import aram_coach
        c = aram_coach.Coach.__new__(aram_coach.Coach)
        c._client = _FakeClient()
        c._out = self.out
        c._vision_state = {}
        c._overlay = {}
        c._api_key = "sk-ant-test"
        c._MODE_NAME = "aram"
        return c

    def test_run_coach_records_but_never_touches_production(self) -> None:
        prod = _production_spend_dir()
        before = _snapshot(prod)
        prod_existed = prod.is_dir()

        tracker = ct.get_tracker()
        calls_before = tracker.daily_spend().get("calls", 0)

        coach = self._make_coach()
        coach._run_coach(_state())

        # Half one: the harness provably reached record_call. Without this the
        # containment assertion below would pass on a broken harness.
        self.assertEqual(coach._client.messages.calls, 1,
                         "the fake Anthropic client was never called - the "
                         "coach bailed before the model call, so this test "
                         "proves nothing about ledger containment")
        self.assertGreater(
            tracker.daily_spend().get("calls", 0), calls_before,
            "the coach call did not reach cost_tracker.record_call - either "
            "_record_coach_call stopped calling it or the fake response "
            "usage is no longer readable; fix the harness, do not relax this",
        )

        # Half two: containment. Before the fix this is where the leak shows -
        # the production day-file grows (or the whole dir is created).
        self.assertEqual(prod_existed, prod.is_dir(),
                         "the test run created the production spend dir")
        self.assertEqual(
            before, _snapshot(prod),
            "a test mutated the production cost ledger at data/spend/ - "
            "the coach call was booked as real operator spend",
        )


if __name__ == "__main__":
    unittest.main()
