"""Item 196 orphan-artifact drift guard.

Pins 7 dead artifacts as PERMANENTLY removed:
  - 2 one-off repair scripts (patch_comp_control + fix_comp_positioning)
  - 3 stale .bak database snapshots (atomic-write insurance, never restored)
  - 2 stale runtime artifacts (audit report + Peer bridge feedback dump)

Each had ZERO callers across .py / .js / .md / .ps1 / .bat / .xml surfaces.
Targets the scripts operated on (tft/comp_control.py + data/tft_set17_meta.json)
do not exist.  The .bak files were atomic-write insurance from s167 DB ops,
not persistent restore points.  The runtime artifacts were one-off dumps with
zero consumers in 22-28 days at item 196 ship time.

Extends item 195's drift-guard pattern to cover .bak + runtime-artifact lanes.
"""
from __future__ import annotations

import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

_DELETED_ORPHAN_ARTIFACTS: tuple[str, ...] = (
    "scripts/patch_comp_control.py",
    "scripts/fix_comp_positioning.py",
    "data/match_history.db.bak-2026-05-09-pre-darkstar-purge",
    "data/match_history.db.bak-2026-05-10-prune-synthetic",
    "data/rewind_history.db.bak-pre-catchup-2026-05-10",
    "ops/runtime/audit_2026_04_27.md",
)


class OrphanArtifactAbsenceTests(unittest.TestCase):
    def test_orphan_artifacts_stay_deleted(self):
        offenders: list[str] = []
        for rel in _DELETED_ORPHAN_ARTIFACTS:
            if (_PROJECT_ROOT / rel).exists():
                offenders.append(rel)
        self.assertEqual(
            offenders, [],
            "Orphan dead artifacts reappeared - investigate: " + "; ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
