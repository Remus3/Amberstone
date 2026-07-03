"""
tests/test_overlay_stats_role_hit_target.py

R38 (DIRECTOR REFILL 2026-06-30) - HIT-TARGETS guard for the Electron-overlay
stats mini-panel (w-stats). The 5-phase fixture audit found the panel's lone
interactive control - the role <select> (.sp-role, wired at
web/js/panels/stats_panel.js) - rendered ~20px tall, under the --hit-min 42px
tap floor (docs/UI_SCALE_SPEC_V2.md line 112), while its sibling overlay
controls already pad to --hit-min. R38 routes .sp-role through
min-height: var(--hit-min).

The compact .es-chip tap-tracker chips (enemy_spells.js) are a DELIBERATE,
operator-tuned sub-floor exception (the A5-locked compact in-game tracker; five
rows x 42px chips would swamp the overlay) and carry an inline rationale
instead of a size bump - the same sanctioned sub --hit-min relaxation R36 used
for the launcher square. Not guarded here (it is intentionally below the floor).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OVERLAY_CSS = ROOT / "web" / "css" / "overlay.css"

# The bare `.sp-role` rule block (NOT the sibling `.sp-role option` rule).
_SP_ROLE_RULE = re.compile(
    r'body\[data-shell="overlay"\]\s+\.ovx-statspanel\s+\.sp-role\s*\{([^}]*)\}'
)

# R72: keyboard-focus ring on the same control (R71 focus-ring parity).
_SP_ROLE_FOCUS_RULE = re.compile(
    r'body\[data-shell="overlay"\]\s+\.ovx-statspanel\s+'
    r'\.sp-role:focus-visible\s*\{([^}]*)\}'
)


def test_stats_role_select_meets_hit_min():
    """The overlay stats role <select> reserves the --hit-min 42px tap floor."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    m = _SP_ROLE_RULE.search(css)
    assert m, ".sp-role rule not found in overlay.css"
    body = m.group(1)
    assert "min-height" in body and "var(--hit-min)" in body, (
        ".sp-role (the overlay stats role selector, the panel's one clickable) "
        "must reserve min-height: var(--hit-min) (42px) - HIT-TARGETS floor "
        "(UI_SCALE_SPEC_V2 line 112)"
    )


def test_stats_role_select_has_focus_ring():
    """The overlay stats role <select> shows the spec --focus-ring on
    keyboard focus (R72 audit; R71 focus-ring parity precedent)."""
    css = OVERLAY_CSS.read_text(encoding="utf-8")
    m = _SP_ROLE_FOCUS_RULE.search(css)
    assert m, ".sp-role:focus-visible rule not found in overlay.css"
    body = m.group(1)
    assert "var(--focus-ring)" in body, (
        ".sp-role:focus-visible must apply the spec focus indicator via "
        "var(--focus-ring) (tokens.css)"
    )
