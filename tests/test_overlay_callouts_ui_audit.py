# arch: R223 - Section-3b 5-phase UI audit of the overlay callouts panel | section=web | frozen=no
"""R223 - 5-phase UI audit guards for the in-game OVERLAY callouts panel.

Scope: `web/js/panels/callouts.js` + `web/css/panels/callouts.css`, the two
OVERLAY widgets they paint - `#rn-lead` (registry id `w-lead`) and
`#rn-callouts` (`w-callouts`), both declared in
`web/js/lib/overlay_layout.js:50,53`. The Chrome :8888 dashboard is retired as
an audit surface, so every judgement below is made against OVERLAY pixels
first: a fixed-width `.ovx-widget` box (`--ovx-w` default 210px,
`web/css/overlay.css:170`) with `overflow-x: hidden` (`overlay.css:193`).

Two MUST-FIX findings are pinned here, plus regression guards for the phases
that passed so a later edit cannot silently un-pass them.

MUST-FIX 1 (phase 1 STRUCTURE) - `renderLead` assigned `mount.className`
wholesale. `overlay_layout.js` owns classes on that SAME node: `_placeAll`
adds `ovx-widget` (line 625) and `_applyPos` toggles `ovx-hidden` (line 296).
A wholesale write destroys both, so the pill loses `position: fixed` + the
Hextech frame and drops into the collapsed static flow, and an
operator-HIDDEN lead widget flashes back visible, until the debounced
MutationObserver (`overlay_layout.js:938-948`) repairs it up to 150ms later.
Measured population: callouts.js was the ONLY renderer in the tree that wrote
`className` on a registered widget mount (2 of 2 instances); the six sibling
overlay panels never touch their mount's class list.

MUST-FIX 2 (phase 5 HIERARCHY) - the lead pill overflowed its 210px overlay
widget and inverted its own hierarchy. MEASURED headless (Chromium, real
tokens.css + overlay.css + callouts.css, real directive strings from
`core/lead_projection.py`): `#rn-lead` scrollWidth 228 vs clientWidth 226, the
`.rc-lead-line` hero squeezed to 61.8px (27 pct of the interior) while the
uppercase `.rc-lead-tag` metadata held 140.4px (62 pct), and the pill stood
216.5px tall - a 12-line ragged column four characters wide. `flex-wrap: wrap`
plus a `margin-left: auto` on the tag drops it to 87px tall with the directive
line on a full-width row, overflow gone. The wide (dashboard) geometry is
byte-identical before and after, so the fix is narrow-container-only.

Test shape follows tests/test_coach_choices_trigger_render.py (node ESM import
of the module's `_internals` / exports against a hand-rolled DOM stub) and
tests/test_overlay_a3_coach_tag_strip.py (pathlib source + CSS rule asserts).
No jsdom, no playwright dependency: the one geometry test that wants a browser
skips cleanly when Chromium is absent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CALLOUTS_JS = REPO / "web" / "js" / "panels" / "callouts.js"
CALLOUTS_CSS = REPO / "web" / "css" / "panels" / "callouts.css"
OVERLAY_LAYOUT_JS = REPO / "web" / "js" / "lib" / "overlay_layout.js"
INDEX_HTML = REPO / "web" / "index.html"
TOKENS_CSS = REPO / "web" / "css" / "tokens.css"
OVERLAY_CSS = REPO / "web" / "css" / "overlay.css"

# --fs-xs is the v2.1 typography floor (docs/UI_SCALE_SPEC_V2.md, 16px).
FS_FLOOR_PX = 16

# The widest real lead directive + its state tag, taken from
# core/lead_projection.py (55 distinct lines, max 54 chars, longest word
# "last-hitting,"). Used by the geometry test so the measurement is about the
# data that actually ships, not a contrived long word.
REAL_LEAD_LINE = "Slight lead: play with your partner, take even fights."
REAL_LEAD_TAG = "behind - large"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _css() -> str:
    return CALLOUTS_CSS.read_text(encoding="utf-8")


def _js() -> str:
    return CALLOUTS_JS.read_text(encoding="utf-8")


def _rule(css: str, selector: str) -> str:
    """Declaration body of the first rule whose head is `selector`, with
    comments stripped so an assert keys off declarations and not comment prose.
    """
    i = css.find(selector)
    assert i != -1, f"selector {selector!r} not found in callouts.css"
    j = css.find("}", i)
    assert j != -1, f"no closing brace after {selector!r}"
    return re.sub(r"/\*.*?\*/", "", css[i:j], flags=re.S)


def _run_node(script: str) -> dict:
    """Import callouts.js as an ES module in node and return its JSON stdout."""
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is present on Legion
        pytest.skip("node not on PATH")
    full = script.replace("__URI__", CALLOUTS_JS.resolve().as_uri())
    res = subprocess.run(
        [node, "--input-type=module", "-e", full],
        capture_output=True, text=True, cwd=str(REPO), timeout=30,
    )
    assert res.returncode == 0, f"node failed: {res.stderr.strip()}"
    return json.loads(res.stdout)


# A minimal element stub with a REAL classList so a renderer that clobbers
# foreign classes is caught. Mirrors what overlay_layout._placeAll leaves on the
# mount: the ovx-widget frame class plus a persisted ovx-hidden.
_DOM_STUB = """
function mkEl(initialClasses) {
  const el = {
    _cls: new Set(initialClasses.split(' ').filter(Boolean)),
    innerHTML: '', hidden: false, htmlWrites: 0,
  };
  el.classList = {
    add: (...c) => c.forEach((x) => el._cls.add(x)),
    remove: (...c) => c.forEach((x) => el._cls.delete(x)),
    contains: (x) => el._cls.has(x),
    toggle: (x, on) => (on ? el._cls.add(x) : el._cls.delete(x)),
  };
  Object.defineProperty(el, 'className', {
    get: () => Array.from(el._cls).join(' '),
    set: (v) => { el._cls = new Set(String(v).split(' ').filter(Boolean)); },
  });
  let _html = '';
  Object.defineProperty(el, 'innerHTML', {
    get: () => _html,
    set: (v) => { _html = v; el.htmlWrites += 1; },
  });
  return el;
}
function installDom(lead, callouts) {
  globalThis.document = {
    getElementById: (id) => (id === 'rn-lead' ? lead
                          : id === 'rn-callouts' ? callouts : null),
  };
}
const snap = (el) => ({ cls: Array.from(el._cls).sort(), html: el.innerHTML,
                        hidden: el.hidden, writes: el.htmlWrites });
"""


# --------------------------------------------------------------------------- #
# PHASE 1 - STRUCTURE
# --------------------------------------------------------------------------- #
def test_render_lead_preserves_overlay_owned_classes():
    """MUST-FIX 1. A populated lead render must ADD its state classes without
    destroying `ovx-widget` / `ovx-hidden`, which overlay_layout.js owns on the
    same node (overlay_layout.js:296,625)."""
    out = _run_node(
        "import {renderLead} from '__URI__';"
        + _DOM_STUB
        + "const lead = mkEl('ovx-widget ovx-hidden');"
        "installDom(lead, mkEl(''));"
        "renderLead({lead_projection:{state:'ahead',magnitude:'clear',"
        "  line:'Clear lead: pressure them, take fights while ahead.'}});"
        "process.stdout.write(JSON.stringify(snap(lead)));"
    )
    assert "ovx-widget" in out["cls"], (
        "renderLead destroyed the overlay frame class - the pill loses "
        "position:fixed until the 150ms MutationObserver repairs it"
    )
    assert "ovx-hidden" in out["cls"], (
        "renderLead un-hid a widget the operator hid via the launcher menu"
    )
    assert "rc-lead" in out["cls"]
    assert "rc-lead-ahead" in out["cls"]


def test_render_lead_clear_preserves_overlay_owned_classes():
    """MUST-FIX 1, empty half. Clearing the pill must drop only its OWN state
    classes."""
    out = _run_node(
        "import {renderLead} from '__URI__';"
        + _DOM_STUB
        + "const lead = mkEl('ovx-widget ovx-hidden');"
        "installDom(lead, mkEl(''));"
        "renderLead({lead_projection:{state:'behind',magnitude:'large',"
        "  line:'Behind: play for scaling.'}});"
        "renderLead({lead_projection:{}});"
        "process.stdout.write(JSON.stringify(snap(lead)));"
    )
    assert "ovx-widget" in out["cls"]
    assert "ovx-hidden" in out["cls"]
    assert "rc-lead" not in out["cls"], "stale state class survived the clear"
    assert "rc-lead-behind" not in out["cls"]
    assert out["hidden"] is True
    assert out["html"] == ""


def test_no_wholesale_classname_assignment_on_the_mount():
    """MUST-FIX 1, source form. `mount.className = ...` is the exact write that
    clobbers a foreign class; classList add/remove is the only safe mutation on
    a node another module also writes to."""
    src = _js()
    assert not re.search(r"\bmount\.className\s*=(?!=)", src), (
        "wholesale className write on an overlay widget mount - use classList"
    )


def test_state_class_helper_still_maps_all_three_states():
    """Behaviour guard for the classList rewrite: the ahead / behind / even
    mapping must be unchanged, and anything unknown must fall to even."""
    out = _run_node(
        "import {_internals} from '__URI__';"
        "const f=_internals._leadStateClass;"
        "process.stdout.write(JSON.stringify({a:f('ahead'),b:f('behind'),"
        "  e:f('even'),junk:f('sideways'),none:f(undefined)}));"
    )
    assert out == {
        "a": "rc-lead-ahead", "b": "rc-lead-behind", "e": "rc-lead-even",
        "junk": "rc-lead-even", "none": "rc-lead-even",
    }


def test_both_mounts_ship_hidden_in_the_markup():
    """No first-paint empty box: an overlay widget with no data must never
    paint its Hextech frame around nothing. The mounts carry `hidden` in the
    static markup, which is what covers the render-before-any-state case (the
    JS clear path only fires on a populated -> empty transition)."""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert re.search(r'<div id="rn-lead"[^>]*\bhidden\b', html)
    assert re.search(r'<div id="rn-callouts"[^>]*\bhidden\b', html)


def test_render_is_idempotent_across_a_steady_state_tick():
    """No-reflow / no-churn guard. A repeated identical payload must not
    rewrite innerHTML: every rebuild destroys the .ovx-handle child that
    overlay_layout._makeHandle appended and forces a re-place pass."""
    out = _run_node(
        "import {renderLead, renderCallouts} from '__URI__';"
        + _DOM_STUB
        + "const lead = mkEl('ovx-widget'); const co = mkEl('ovx-widget');"
        "installDom(lead, co);"
        "const s={lead_projection:{state:'even',magnitude:'slight',line:'Even.'},"
        "  callouts:[{tag:'baron',kind:'objective',line:'Baron up',eta_s:90}]};"
        "for (let i=0;i<5;i++) { renderLead(s); renderCallouts(s); }"
        "process.stdout.write(JSON.stringify({lead:snap(lead),co:snap(co)}));"
    )
    assert out["lead"]["writes"] == 1, "lead pill re-rendered on a steady tick"
    assert out["co"]["writes"] == 1, "callouts re-rendered on a steady tick"


def test_callouts_render_caps_at_three_rows():
    """STRUCTURE contract: up to 3 rows. (The overlay clamps further to 2 via
    overlay.css:266; the JS cap is the source-side bound.)"""
    out = _run_node(
        "import {renderCallouts} from '__URI__';"
        + _DOM_STUB
        + "const co = mkEl('ovx-widget'); installDom(mkEl(''), co);"
        "renderCallouts({callouts:[1,2,3,4,5].map((n)=>"
        "  ({tag:'t'+n,kind:'objective',line:'line '+n,eta_s:n}))});"
        "process.stdout.write(JSON.stringify(snap(co)));"
    )
    assert out["html"].count("rc-co-row") == 3


# --------------------------------------------------------------------------- #
# PHASE 2 - TYPOGRAPHY
# --------------------------------------------------------------------------- #
def test_every_font_size_uses_a_scale_token():
    """docs/UI_SCALE_SPEC_V2.md: no hardcoded font-size; every declaration
    resolves through a --fs-* token."""
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    decls = re.findall(r"font-size\s*:\s*([^;]+);", css)
    assert decls, "no font-size declarations found - selector drift?"
    for d in decls:
        assert "var(--fs-" in d, f"hardcoded font-size {d.strip()!r}"


def test_no_font_size_fallback_below_the_xs_floor():
    """A `var(--fs-x, N)` fallback is what renders if tokens.css is late, so it
    is a real rendered size and takes the same 16px floor."""
    css = re.sub(r"/\*.*?\*/", "", _css(), flags=re.S)
    for d in re.findall(r"font-size\s*:\s*var\(--fs-[a-z]+\s*,\s*(\d+)px\)", css):
        assert int(d) >= FS_FLOOR_PX, f"font-size fallback {d}px below the floor"


def test_scale_tokens_used_here_exist_in_tokens_css():
    """A typo'd token silently falls back; pin every token this panel reads."""
    tokens = TOKENS_CSS.read_text(encoding="utf-8")
    used = set(re.findall(r"var\((--fs-[a-z]+)", _css()))
    assert used, "no --fs-* tokens consumed"
    for t in sorted(used):
        assert re.search(rf"{re.escape(t)}\s*:", tokens), f"{t} not defined"


# --------------------------------------------------------------------------- #
# PHASE 3 - HIT-TARGETS
# --------------------------------------------------------------------------- #
def test_panel_declares_no_interactive_affordance_without_a_hit_min():
    """Measured: this panel ships ZERO clickable elements (no listener, no
    cursor:pointer, no button/anchor/tabindex), so --hit-min (42px) is vacuous
    today. This guard is what makes the phase executable: the day someone adds
    a click target here, it must arrive with a --hit-min rule."""
    js, css = _js(), _css()
    interactive = (
        "addEventListener" in js
        or re.search(r"\bon(click|pointerdown|mousedown)\s*=", js)
        or "tabindex" in js.lower()
        or re.search(r"<\s*(button|a)\b", js)
        or "cursor: pointer" in css
    )
    if interactive:
        assert "--hit-min" in css, (
            "callouts gained an interactive affordance without a --hit-min rule"
        )


# --------------------------------------------------------------------------- #
# PHASE 4 - ASCII
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path", [CALLOUTS_JS, CALLOUTS_CSS])
def test_panel_files_are_pure_7bit_ascii(path):
    """Neither file appears in the RM-125 live-glyph census
    (docs/RM125_web_live_glyph_adjudication.md section 2, 16 files), so there is
    no KEEP / LOAD-BEARING glyph to preserve here and nothing may be
    introduced."""
    bad = [(i, b) for i, b in enumerate(path.read_bytes()) if b > 127]
    assert not bad, f"{path.name} carries non-ASCII bytes at {bad[:5]}"


def test_meta_separator_is_the_ascii_clause_break():
    """The lead tag joins state + magnitude with the repo's spaced hyphen, NOT
    the U+00B7 MIDDLE DOT that 11 sibling panels use (RM-125 section 5.3, 107
    instances, an operator-gated repo-wide sweep). Do not "improve" this one
    into the deferred convention."""
    src = _js()
    assert "${state} - ${mag}" in src
    assert "\u00b7" not in src


# --------------------------------------------------------------------------- #
# PHASE 5 - HIERARCHY
# --------------------------------------------------------------------------- #
def test_lead_pill_wraps_rather_than_overflowing_a_narrow_widget():
    """MUST-FIX 2, source form. In a 210px .ovx-widget the nowrap state tag
    takes 140px of a 226px interior, so a single flex row cannot hold both:
    the directive line collapses to its min-content width and the row overflows
    into overflow-x:hidden. Wrapping gives the hero line a full-width row."""
    body = _rule(_css(), ".rc-lead {")
    assert "flex-wrap: wrap" in body, "lead pill cannot wrap in a narrow widget"
    tag = _rule(_css(), ".rc-lead-tag {")
    assert "margin-left: auto" in tag, (
        "the tag must stay right-aligned once it wraps onto its own row "
        "(justify-content: space-between only right-aligns a 2-item row)"
    )


def test_callout_row_ellipsis_is_reachable():
    """Companion guard for the row list. `.rc-co-line` sets overflow:hidden,
    which zeroes a flex item's automatic minimum size, so the ellipsis DOES
    engage without min-width:0 (measured: row scrollWidth == clientWidth at
    210px). Dropping overflow:hidden would silently re-arm the overflow, so pin
    the three declarations that make the truncation work."""
    body = _rule(_css(), ".rc-co-line {")
    assert "overflow: hidden" in body
    assert "text-overflow: ellipsis" in body
    assert "white-space: nowrap" in body


def _measure(scale: float) -> dict:
    """Render the two widgets with the REAL stylesheets in headless Chromium."""
    playwright = pytest.importorskip("playwright.sync_api")
    page_html = f"""
<style>
{TOKENS_CSS.read_text(encoding="utf-8")}
{_css()}
{OVERLAY_CSS.read_text(encoding="utf-8")}
html, body {{ margin: 0; }}
body {{ zoom: {scale}; }}
</style>
<body data-shell="overlay" class="ovx-ready">
<main><div id="right-now"><div class="panel-body">
  <div id="rn-lead" class="ovx-widget rc-lead rc-lead-behind" style="left:786px;top:44px">
    <span class="rc-lead-line">{REAL_LEAD_LINE}</span>
    <span class="rc-lead-tag">{REAL_LEAD_TAG}</span>
  </div>
</div></div></main>
</body>
"""
    js = """() => {
      const lead = document.getElementById('rn-lead');
      const line = lead.querySelector('.rc-lead-line');
      const box = lead.getBoundingClientRect();
      return { scrollW: lead.scrollWidth, clientW: lead.clientWidth,
               lineW: line.getBoundingClientRect().width,
               height: box.height, position: getComputedStyle(lead).position };
    }"""
    try:
        with playwright.sync_playwright() as p:
            browser = p.chromium.launch()
            pg = browser.new_page(viewport={"width": 1920, "height": 1080})
            pg.set_content(page_html)
            out = pg.evaluate(js)
            browser.close()
    except Exception as exc:  # noqa: BLE001 - no browser binary is a skip, not a failure
        pytest.skip(f"headless chromium unavailable: {exc}")
    return out


@pytest.mark.parametrize("scale", [0.8, 1.0, 1.6])
def test_lead_pill_fits_the_overlay_widget_across_the_scale_band(scale):
    """MUST-FIX 2, measured form. The overlay scale band is [0.8, 1.6]
    (overlay_layout._setScale clamps 0.5-1.6). At every point in it the pill
    must fit its fixed-width widget - overflow-x:hidden means an overflow is a
    silent clip of the state tag, not a scrollbar."""
    m = _measure(scale)
    assert m["position"] == "fixed", "the .ovx-widget frame did not apply"
    assert m["scrollW"] <= m["clientW"], (
        f"lead pill overflows its widget at scale {scale}: "
        f"{m['scrollW']} > {m['clientW']}"
    )


def test_lead_directive_line_outweighs_its_metadata_tag():
    """MUST-FIX 2, hierarchy form. The directive line is the hero of the pill
    (weight 600, the larger tier); the state tag is metadata. Pre-fix the line
    held 61.8px of a 226px interior (27 pct) against the tag's 140.4px. The
    line must hold the majority of the interior."""
    m = _measure(1.0)
    assert m["lineW"] >= 0.5 * m["clientW"], (
        f"directive line starved to {m['lineW']:.1f}px of {m['clientW']}px"
    )


def test_lead_pill_is_not_a_ragged_column():
    """MUST-FIX 2, height form. Measured 216.5px tall pre-fix (a 12-line column
    four characters wide) against 87px after. 140px is a generous ceiling that
    still fails the pre-fix render."""
    m = _measure(1.0)
    assert m["height"] <= 140, f"lead pill is {m['height']:.1f}px tall"


# --------------------------------------------------------------------------- #
# Cross-file contract this panel must keep honouring (read-only assertions).
# --------------------------------------------------------------------------- #
def test_overlay_layout_still_owns_these_two_mounts():
    """If the registry stops declaring w-lead / w-callouts, every overlay-first
    judgement above is scoped to the wrong surface."""
    src = OVERLAY_LAYOUT_JS.read_text(encoding="utf-8")
    assert 'id: "w-lead", sel: "#rn-lead"' in src
    assert 'id: "w-callouts", sel: "#rn-callouts"' in src


def test_overlay_layout_still_owns_the_classes_this_panel_must_not_touch():
    """Pins WHY MUST-FIX 1 matters: these are the foreign writes on the same
    node that a wholesale className assignment would destroy."""
    src = OVERLAY_LAYOUT_JS.read_text(encoding="utf-8")
    assert 'el.classList.add("ovx-widget")' in src
    assert 'el.classList.toggle("ovx-hidden", p.hidden)' in src
