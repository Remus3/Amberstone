"""
tests/test_stale_fade_gentle_t12.py

s136-T12 (operator 2026-10-25, verbatim: "dont have the panels fade as much
when the data is out of date timer'd"). Pins the gentle stale / idle dim.

Three timer-driven fade mechanisms share one rule now - same timers, same
stale cue, and no content opacity below 0.85 at the deepest stage:

  1. Dashboard CADENCE sweep (web/js/main.js applyStaleness every 500 ms,
     thresholds in web/js/lib/state.js CADENCE) stamps .stale / .severe on
     #right-now / #next / #item-build / #minimap. map_state.css dim was
     0.6 / 0.45 + grayscale(0.4); now 0.89 / 0.85, no filter. The cue stays
     the .staleness age badge (gold "Ns" at stale, red at severe).
  2. Overlay idle recede (web/js/lib/overlay_idle.js, 8 s quiet) stamps
     body[data-rc-idle]; overlay.css section 6 was 0.12, now 0.85.
  3. The overlay #rn-* widget mounts sit inside #right-now .panel-body, so
     mechanism 1 dimmed them too, with the badge hidden (the head is off in the
     overlay) and compounding with 2 (0.45 x 0.12 = 0.054). The overlay now
     takes no stale dim and shows a STALE ::after tag instead (section 6b).

Plus the minimap screenshot's own fetch-failure dim (grid.css), which nested
inside the CADENCE-dimmed #minimap body: now a light desaturation + a
" - STALE" caption suffix, no own opacity, so it cannot compound below 0.85.

Static pins (no browser); the computed-style proof is
tests/snapshot_panels/test_stale_fade_view_t12.py.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CSS_DIR = WEB / "css"
MAP_STATE_CSS = CSS_DIR / "panels" / "map_state.css"
GRID_CSS = CSS_DIR / "panels" / "grid.css"
OVERLAY_CSS = CSS_DIR / "overlay.css"
STATE_JS = WEB / "js" / "lib" / "state.js"
MAIN_JS = WEB / "js" / "main.js"
IDLE_JS = WEB / "js" / "lib" / "overlay_idle.js"

FLOOR = 0.85
OV = 'body[data-shell="overlay"]'

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _rules(path: Path) -> dict[str, list[dict[str, str]]]:
    """selector -> list of {property: value} for every rule naming it."""
    css = _COMMENT.sub("", path.read_text(encoding="utf-8"))
    out: dict[str, list[dict[str, str]]] = {}
    for sels, body in _RULE.findall(css):
        decls = {}
        for part in body.split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                decls[k.strip().lower()] = " ".join(v.split())
        for sel in sels.split(","):
            key = " ".join(sel.split())
            if key and not key.startswith("@"):
                out.setdefault(key, []).append(decls)
    return out


def _decl(path: Path, selector: str, prop: str) -> str | None:
    """The LAST value of prop across every rule naming exactly selector."""
    val = None
    for decls in _rules(path).get(selector, []):
        if prop in decls:
            val = decls[prop]
    return val


def _opacity(value: str) -> float:
    return float(value.replace("!important", "").strip())


# ------------------------------------------------------------ timers + cue
def test_cadence_thresholds_unchanged():
    """The timers are NOT part of this change - only the dim depth is."""
    js = STATE_JS.read_text(encoding="utf-8")
    got = {
        m.group(1): (int(m.group(2)), int(m.group(3)))
        for m in re.finditer(
            r"^\s*(\w+):\s*\{\s*stale:\s*(\d+),\s*severe:\s*(\d+)\s*\}", js, re.M)
    }
    assert got == {
        "right_now": (4, 12), "next": (16, 48),
        "item_build": (90, 300), "minimap": (4, 12),
    }


def test_idle_timer_unchanged():
    js = IDLE_JS.read_text(encoding="utf-8")
    assert re.search(r"const IDLE_DELAY_MS = 8000;", js)


def test_dashboard_stale_cue_kept():
    """The age badge is the cue: main.js still writes "<age>s" + the stage class,
    and map_state.css still colours the stale / severe stages."""
    js = MAIN_JS.read_text(encoding="utf-8")
    assert 'elm.textContent = age + "s";' in js
    assert 'elm.className = "staleness " + klass;' in js
    assert _decl(MAP_STATE_CSS, ".staleness.stale", "color") == "var(--gold)"
    assert _decl(MAP_STATE_CSS, ".staleness.severe", "color") == "var(--bad)"


# ------------------------------------------------------------ dashboard dim
def test_dashboard_stale_dim_is_gentle():
    stale = _decl(MAP_STATE_CSS, ".panel.stale .panel-body", "opacity")
    severe = _decl(MAP_STATE_CSS, ".panel.severe .panel-body", "opacity")
    assert stale is not None and severe is not None
    assert _opacity(stale) == 0.89, stale    # was 0.6
    assert _opacity(severe) == 0.85, severe  # was 0.45
    assert _opacity(severe) <= _opacity(stale) < 1.0  # still two ordered stages


def test_dashboard_stale_dim_has_no_filter():
    """No grayscale / blur on panel text (and no filter at all: a filter on
    .panel-body becomes the containing block of the overlay's fixed mounts)."""
    for sel in (".panel.stale .panel-body", ".panel.severe .panel-body"):
        assert _decl(MAP_STATE_CSS, sel, "filter") is None, sel


# ------------------------------------------------------------ overlay
def test_overlay_idle_recede_is_gentle():
    sel = f'{OV}[data-rc-idle="1"] .ovx-widget'
    val = _decl(OVERLAY_CSS, sel, "opacity")
    assert val is not None and _opacity(val) == FLOOR, val  # was 0.12
    assert _decl(OVERLAY_CSS, f"{OV} .ovx-widget", "transition") == "opacity 400ms ease"


def test_overlay_takes_no_stale_dim():
    """The overlay's #right-now body must not dim on staleness, or it compounds
    with the idle recede below the floor."""
    for stage in ("stale", "severe"):
        val = _decl(OVERLAY_CSS, f"{OV} #right-now.{stage} .panel-body", "opacity")
        assert val is not None and _opacity(val) == 1.0, (stage, val)


def test_overlay_stale_tag():
    for stage in ("stale", "severe"):
        sel = f"{OV} #right-now.{stage} .ovx-widget::after"
        assert _decl(OVERLAY_CSS, sel, "content") == '"stale"', stage
        assert _decl(OVERLAY_CSS, sel, "font-size") == "var(--fs-ov-head)", stage
        assert _decl(OVERLAY_CSS, sel, "text-transform") == "uppercase", stage
        assert _decl(OVERLAY_CSS, sel, "pointer-events") == "none", stage
        assert _decl(OVERLAY_CSS, sel, "display") == "block", stage
        assert _decl(OVERLAY_CSS, sel, "width") == "100%", stage  # own row in #rn-lead
        color = _decl(OVERLAY_CSS, sel, "color") or ""
        assert "--ovx-red" not in color and "--signal-bad" not in color, color
    assert _decl(OVERLAY_CSS, f"{OV} #right-now.stale .ovx-widget::after",
                 "color") == "rgba(var(--ovx-gold), 0.90)"
    assert _decl(OVERLAY_CSS, f"{OV} #right-now.severe .ovx-widget::after",
                 "color") == "rgb(var(--ovx-warn))"


# ------------------------------------------------------------ minimap image
def test_minimap_image_stale_is_light_and_labelled():
    sel = ".minimap-img-wrap.stale #mm-img"
    assert _decl(GRID_CSS, sel, "opacity") is None  # was 0.5 (compounded)
    assert _decl(GRID_CSS, sel, "filter") == "grayscale(0.15)"  # was 0.5
    cap = ".minimap-img-wrap.stale .minimap-img-caption::after"
    assert _decl(GRID_CSS, cap, "content") == '" - STALE"'
    assert _decl(GRID_CSS, cap, "color") == "var(--gold)"


# ------------------------------------------------------------ floor sweep
_STAGE_SEL = re.compile(r"\.(stale|severe)\b|data-rc-idle")
_GRAY = re.compile(r"grayscale\(\s*([\d.]+)\s*\)")


def test_every_stale_or_idle_dim_respects_the_floor():
    """Drift guard over every web/css stylesheet: a rule keyed on a stale /
    severe stage or the idle attribute may not set opacity below 0.85, blur,
    or grayscale more than 0.2. Anchored so an empty sweep cannot pass."""
    opacity_rules = []
    offenders = []
    for path in sorted(CSS_DIR.rglob("*.css")):
        for sel, bodies in _rules(path).items():
            if not _STAGE_SEL.search(sel) or ".staleness" in sel:
                continue
            for decls in bodies:
                rel = f"{path.relative_to(ROOT).as_posix()} {sel}"
                if "opacity" in decls:
                    opacity_rules.append(rel)
                    if _opacity(decls["opacity"]) < FLOOR:
                        offenders.append(f"{rel} opacity {decls['opacity']}")
                filt = decls.get("filter", "")
                if "blur(" in filt:
                    offenders.append(f"{rel} filter {filt}")
                for g in _GRAY.findall(filt):
                    if float(g) > 0.2:
                        offenders.append(f"{rel} filter {filt}")
    assert not offenders, offenders
    expected = {
        "web/css/panels/map_state.css .panel.stale .panel-body",
        "web/css/panels/map_state.css .panel.severe .panel-body",
        f'web/css/overlay.css {OV}[data-rc-idle="1"] .ovx-widget',
        f"web/css/overlay.css {OV} #right-now.stale .panel-body",
    }
    assert expected <= set(opacity_rules), sorted(opacity_rules)


def test_touched_text_is_ascii():
    """grid.css / overlay.css / overlay_idle.js are whole-file ASCII; map_state.css
    carries two older allowlisted content glyphs, so only the T12 block is held."""
    for p in (GRID_CSS, OVERLAY_CSS, IDLE_JS):
        p.read_bytes().decode("ascii")
    css = MAP_STATE_CSS.read_text(encoding="utf-8")
    start = css.index("s136-T12")
    end = css.index(".panel.severe .panel-body", start)
    css[start:end].encode("ascii")
