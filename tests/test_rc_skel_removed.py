"""
tests/test_rc_skel_removed.py

Guard: the dormant rc-skel loading-skeleton mechanism is permanently removed
(dead-code sweep, 2026-07-01, chip task from the OQ4 motion sweep).

Why it was dead (double-verified by grep before removal):
  - no markup or JS anywhere set the data-rc-skel attribute, so the
    main.js init querySelectorAll matched zero elements;
  - the "rc:state-tick" strip event was NEVER dispatched anywhere (two
    addEventListener sites, zero dispatchEvent), so if the attribute had
    ever been adopted, skeletons would have stuck forever;
  - panel_visibility.js carried a self-described "belt-and-suspenders"
    listener on the same never-event; its live path is setMode() calling
    applyPanelVisibility directly (unchanged).

The "-" no-data sentinel remains the operator-approved loading/no-data
display. If a skeleton affordance is ever wanted, re-add it from git
history WITH a real dispatcher (option b of the chip task).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

BANNED = ("rc-skel", "data-rc-skel", "rc:state-tick")


def _web_sources():
    for pattern in ("js/**/*.js", "css/**/*.css", "*.html"):
        yield from WEB.glob(pattern)


def test_rc_skel_mechanism_gone():
    hits = []
    for p in _web_sources():
        text = p.read_text(encoding="utf-8", errors="replace")
        for token in BANNED:
            if token in text:
                hits.append(f"{p.relative_to(ROOT)} :: {token}")
    assert not hits, f"dormant rc-skel mechanism resurfaced: {hits}"


def test_panel_visibility_live_path_intact():
    """The removal must not touch the live re-apply path: setMode() calls
    applyPanelVisibility directly, and initPanelVisibility still builds +
    applies at boot."""
    pv = (WEB / "js" / "panels" / "panel_visibility.js").read_text(encoding="utf-8")
    assert "function initPanelVisibility()" in pv
    assert "buildPanelVisibilitySettings();" in pv
    assert "applyPanelVisibility();" in pv
    mainjs = (WEB / "js" / "main.js").read_text(encoding="utf-8")
    assert "applyPanelVisibility" in mainjs, "setMode() live re-apply path lost"
