"""BATCH C #2 (2026-07-06): the overlay "You vs Avg" stats panel must default
its compare role to the operator's DETECTED role (SR assigned lane, else the
champion's class in ARAM) instead of a hardcoded MID, while keeping the manual
dropdown override.

Companion to the node runner web/js/panels/stats_panel.test.mjs (run via
`node --test`), mirroring the objective_gauges / spike_curve wrapper idiom: this
pins the JS wiring + the mjs coverage by source-check so a regression trips the
Python CI suite even though CI does not execute node.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL_JS = ROOT / "web" / "js" / "panels" / "stats_panel.js"
PANEL_MJS = ROOT / "web" / "js" / "panels" / "stats_panel.test.mjs"


def _read(p: Path) -> str:
    assert p.exists(), f"missing {p}"
    return p.read_text(encoding="utf-8")


def test_stats_panel_has_role_detection_wiring():
    src = _read(PANEL_JS)
    # The detection helper + the two lookup maps exist.
    assert "function _detectRole(" in src
    assert "_POS_ROLE" in src and "_CLASS_ROLE" in src
    # The SR position -> role mapping covers all five lanes.
    for pos in ("TOP", "JUNGLE", "MIDDLE", "BOTTOM", "UTILITY"):
        assert pos in src, f"_POS_ROLE must map {pos}"
    # The ARAM/no-lane champion-class fallback (Kai'Sa/Aphelios -> bot, not MID).
    assert "Marksman" in src and "championTags" in src
    # First-render seeding + the manual-override latch.
    assert "_roleUserSet" in src
    assert "_detectRole(lc)" in src


def test_stats_panel_manual_override_stops_auto_seed():
    src = _read(PANEL_JS)
    # The dropdown change handler sets the latch so detection stops overriding.
    assert "_roleUserSet = true" in src
    # Seeding is gated on the latch being unset.
    assert "if (!_roleUserSet)" in src


def test_stats_panel_mjs_exists_and_covers_cases():
    mjs = _read(PANEL_MJS)
    assert "_detectRole" in mjs
    # SR lane case, ARAM class fallback case, and the null case are all pinned.
    assert "BOTTOM" in mjs
    assert "Marksman" in mjs
    assert "null" in mjs
