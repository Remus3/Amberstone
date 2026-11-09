"""s156 S5 (C7) item 4: non-TFT coach strategy text vs the current patch.

Measured 2026-11-08 against data/daemon_slayer/16.21.1 and Riot patch notes:
  - Arena: RC's own queue map (lcu/snapshot_shape.py 1750) says the live queue
    is Arena 3x6 (teams of three); patch 26.12 notes mention a 1v3 last-player
    revive. The prompt said "Arena 2v2v2v2 ... your pair / enemy pair".
  - The Arena and ARAM Mayhem prompts listed "best augments" that are SR rune
    names (Cut Down, Sudden Impact, Eyeball Collection, Absolute Focus, Bone
    Plating, Shield Bash, Unflinching): none is in arena_augments.json,
    cherry_augments.json or mayhem_augments.json.
No coach prompt may carry an SR objective timing (those live in
core/sr_schedule.py) and none may name a retired objective.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COACHES = ROOT / "coaches"
RUNE_NAMES = ("Cut Down", "Sudden Impact", "Eyeball Collection",
              "Absolute Focus", "Bone Plating", "Shield Bash", "Unflinching")


def _src(name: str) -> str:
    return (COACHES / name).read_text(encoding="utf-8")


class ArenaPromptTests(unittest.TestCase):
    def test_no_stale_2v2v2v2_pair_wording_in_prompt(self):
        s = _src("arena_coach.py")
        prompt = s[s.index("_SYSTEM_PROMPT = "):s.index("_USER_TEMPLATE = ")]
        self.assertNotIn("2v2v2v2", prompt)
        self.assertNotIn("Your pair", prompt)
        self.assertNotIn("enemy pair", prompt)
        self.assertNotIn("in 2v2", prompt)
        self.assertIn("3x6", prompt)

    def test_no_rune_names_as_augments(self):
        s = _src("arena_coach.py")
        for n in RUNE_NAMES:
            self.assertNotIn(n, s, n)


class AramPromptTests(unittest.TestCase):
    def test_no_rune_names_as_augments(self):
        s = _src("aram_coach.py")
        for n in RUNE_NAMES:
            self.assertNotIn(n, s, n)


class DataGroundingTests(unittest.TestCase):
    """The rune names really are absent from every augment dataset."""

    def test_rune_names_not_in_augment_data(self):
        base = ROOT / "data" / "daemon_slayer"
        files = sorted(base.glob("*/arena_augments.json")) \
            + sorted(base.glob("*/cherry_augments.json")) \
            + sorted(base.glob("*/mayhem_augments.json"))
        self.assertTrue(files, "augment datasets missing")
        for f in files[-3:]:
            blob = json.dumps(json.loads(f.read_text(encoding="utf-8"))).lower()
            for n in RUNE_NAMES:
                self.assertNotIn(n.lower(), blob, f"{n} in {f.name}")


class NoSrTimingInCoachPromptsTests(unittest.TestCase):
    """Coach prompts carry no SR objective clock and no retired objective."""

    def test_no_objective_timings_or_atakhan(self):
        stale = re.compile(
            r"atakhan|plates? fall|14:00|8:00 .*herald|baron.{0,20}25:00",
            re.IGNORECASE)
        for p in sorted(COACHES.glob("*.py")):
            m = stale.search(p.read_text(encoding="utf-8"))
            self.assertIsNone(m, f"{p.name}: {m.group(0) if m else ''}")


if __name__ == "__main__":
    unittest.main()
