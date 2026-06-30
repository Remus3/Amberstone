"""
tests/test_overlay_launcher_hit_targets.py

R36 (DIRECTOR REFILL 2026-06-30) - HIT-TARGETS guard for the Electron-overlay
launcher control center (#w-launcher + its layout menu). The launcher widget +
its popup menu were shipped in a live session (LEDGER 688) WITHOUT the 5-phase
fixture audit; this is that audit's HIT-TARGETS MUST-FIX, locked as a guard.

docs/UI_SCALE_SPEC_V2.md interaction rule (line 112 + 118): every button /
toggle / slider-thumb is a clickable whose interactive target must meet the
--hit-min floor (42px), even when the visible chrome is smaller. The launcher
menu's action rows (the per-panel show/hide toggle, "Reset all panels",
"Done (back to play)") and the per-panel opacity/scale slider rows were sized
on padding + a single text line (~30-33px tall) - below the 42px tap floor.

Design invariant locked here:
  - every launcher-menu action row (.ovx-menu-row) reserves >= --hit-min height;
  - every launcher-menu slider row (.ovx-menu-slider, the opacity/scale thumb
    drag target) reserves >= --hit-min height;
  - the dead .ovx-menu-panelset rule is gone (the coach/build/threat panel-set
    quick-swap was RETIRED 2026-06-28 - overlay_layout.js _renderMenu emits no
    such element, so the orphaned CSS rule is removed).

The launcher square itself (.ovx-launcher, 34px) is a DELIBERATE operator
exception (HUD summoner-spell sized, inline rationale in overlay.css) and is
intentionally NOT forced to 42px - it stays a small corner glyph.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_CSS = ROOT / "web" / "css" / "overlay.css"


def _rule_body(css, selector_suffix):
    """Return the declaration block of the FIRST rule whose selector ends in
    `selector_suffix` immediately before the `{` (so `.ovx-menu-row {` matches
    but `.ovx-menu-row:hover {` does not)."""
    m = re.search(
        re.escape(selector_suffix) + r"\s*\{([^}]*)\}",
        css,
        re.DOTALL,
    )
    return m.group(1) if m else None


def test_launcher_menu_rows_meet_hit_min():
    """Every launcher-menu action button reserves the --hit-min tap target."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    body = _rule_body(css, ".ovx-menu-row")
    assert body is not None, "the .ovx-menu-row base rule must exist"
    assert re.search(r"min-height:\s*var\(--hit-min\)", body), (
        "launcher menu action rows (.ovx-menu-row) must reserve "
        "min-height: var(--hit-min) (42px) - the show/hide toggle, reset, and "
        "done buttons are clickables and must meet the spec tap floor"
    )


def test_launcher_menu_slider_rows_meet_hit_min():
    """Every launcher-menu slider row (opacity/scale thumb drag) meets the
    --hit-min target (spec line 118: slider thumb target is --hit-min via a
    padded wrapper, even though the visible thumb is 18-20px)."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    body = _rule_body(css, ".ovx-menu-slider")
    assert body is not None, "the .ovx-menu-slider base rule must exist"
    assert re.search(r"min-height:\s*var\(--hit-min\)", body), (
        "launcher menu slider rows (.ovx-menu-slider) must reserve "
        "min-height: var(--hit-min) (42px) - the opacity/scale thumb is a drag "
        "target and must meet the spec tap floor"
    )


def test_dead_panelset_rule_removed():
    """The .ovx-menu-panelset rule is orphaned dead CSS - the coach/build/threat
    panel-set quick-swap was retired 2026-06-28 (overlay_layout.js _renderMenu
    emits no panelset button). The rule must be gone, not just unused."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    assert "ovx-menu-panelset" not in css, (
        "dead .ovx-menu-panelset rule must be removed from overlay.css - the "
        "panel-set quick-swap menu button was retired 2026-06-28"
    )


def test_launcher_menu_rules_still_present():
    """Positive guard so the hit-target assertions are not vacuously true: the
    launcher menu's core rules survive in overlay.css."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    for needed in (".ovx-launcher", ".ovx-launcher-menu", ".ovx-menu-row", ".ovx-menu-slider"):
        assert needed in css, f"launcher menu rule {needed} missing from overlay.css"
