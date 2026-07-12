"""HIT-TARGETS + focus guard for the overlay stats-panel benchmark selectors.

Overlay item 8 rework relocated the stats-panel selection out of the panel: the
old in-panel role <select> (.sp-role in overlay.css) is retired, and the
rank-tier + compare-role selectors now live in the DS Settings strip
(web/js/panels/overlay_ds_controls.js, styled .ovset-sel > select in
web/css/panels/overlay_ds_controls.css). The R38/R72 tap-floor + focus-ring
guard follows them to their new home: each select reserves min-height
var(--hit-min) (42px, docs/UI_SCALE_SPEC_V2.md line 112) and shows the spec
var(--focus-ring) on keyboard focus.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DS_CSS = ROOT / "web" / "css" / "panels" / "overlay_ds_controls.css"

# The .ovset-sel > select rule block (the relocated benchmark selectors).
_SEL_RULE = re.compile(r'\.ovset-sel\s*>\s*select\s*\{([^}]*)\}')
# The keyboard-focus ring on the same control.
_SEL_FOCUS_RULE = re.compile(r'\.ovset-sel\s*>\s*select:focus-visible\s*\{([^}]*)\}')


def test_stats_benchmark_select_meets_hit_min():
    """The DS Settings benchmark <select>s reserve the --hit-min 42px tap floor."""
    css = DS_CSS.read_text(encoding="utf-8")
    m = _SEL_RULE.search(css)
    assert m, ".ovset-sel > select rule not found in overlay_ds_controls.css"
    body = m.group(1)
    assert "min-height" in body and "var(--hit-min" in body, (
        ".ovset-sel > select (the relocated stats-panel rank/role selectors) "
        "must reserve min-height: var(--hit-min) (42px) - HIT-TARGETS floor "
        "(UI_SCALE_SPEC_V2 line 112)"
    )


def test_stats_benchmark_select_has_focus_ring():
    """The DS Settings benchmark <select>s show the spec --focus-ring on keyboard
    focus (R72 focus-ring parity)."""
    css = DS_CSS.read_text(encoding="utf-8")
    m = _SEL_FOCUS_RULE.search(css)
    assert m, ".ovset-sel > select:focus-visible rule not found in overlay_ds_controls.css"
    body = m.group(1)
    assert "var(--focus-ring)" in body, (
        ".ovset-sel > select:focus-visible must apply the spec focus indicator "
        "via var(--focus-ring) (tokens.css)"
    )
