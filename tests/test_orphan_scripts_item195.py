"""Item 195 orphan-script drift guard.

Pins 7 dead one-off repair / fetch / inspect scripts as PERMANENTLY removed.
Each had ZERO callers across .py/.md/.ps1/.bat surfaces and targets that no
longer exist (tft/comp_control.py + tft/tft_overlay.py + ops/staging/ all
absent at item 195 ship time).

If you find yourself adding any of these back, first confirm a real consumer
exists - otherwise the script is dead-on-arrival.
"""
from __future__ import annotations

import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

_DELETED_ORPHAN_FILES: tuple[str, ...] = (
    "scripts/extract_cdragon.py",
    "scripts/fix_comp_control.py",
    "scripts/syntax_and_stage.py",
    "scripts/verify_fixes.py",
    "tools/arena_phase3_fetch.py",
    "tools/arena_phase3_inspect.py",
    "tools/arena_phase3_parse.py",
)


class OrphanScriptAbsenceTests(unittest.TestCase):
    def test_orphan_scripts_stay_deleted(self):
        offenders: list[str] = []
        for rel in _DELETED_ORPHAN_FILES:
            if (_PROJECT_ROOT / rel).exists():
                offenders.append(rel)
        self.assertEqual(
            offenders, [],
            "Orphan dead scripts reappeared - investigate: " + "; ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
