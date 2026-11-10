"""
tests/snapshot_panels/test_zoi_canvas_class_opacity.py
S144-U-259 (s144 uiux): the shared .mm-zoi-canvas class rule in
web/css/panels/grid.css no longer sets opacity 0 (or the 300 ms opacity
transition that faded the retired #minimap stack in), so the overlay ZOI
canvas #am-zoi-canvas, now the class's only bearer, is visible by its own
CSS.

THE DEFECT. The rule was written for the #minimap stack's ZOI canvas,
which map_state.js faded in. S144-U-258 retired that stack, and the rule
then only hid #am-zoi-canvas. That is the computed-opacity-0 trap item 688
hit in the live overlay: the shading drew but was fully transparent, and
the fix (an inline canvas.style.opacity = "1" in panels/minimap_zoi.js)
was recorded as a workaround for "a Chromium quirk" with "no CSS/JS rule"
setting it. This class rule was that rule. The inline pin stays as belt
and braces; the comments now name the real cause.

Pinned by COMPUTED value (lane doc section 6 trap 1: a grep cannot see
what the browser resolves), with the inline style removed first so the
read is the stylesheet's own answer, plus a counter-control proving the
probe sees a class-level opacity rule when one exists.
"""
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

REPO = Path(__file__).resolve().parents[2]


def _rule_bodies(css, selector):
    pat = re.compile(r"(^|[}\s,])" + re.escape(selector) + r"\s*\{([^}]*)\}",
                     re.M)
    return [m.group(2) for m in pat.finditer(css)]


def test_the_class_rule_sets_no_opacity_and_no_opacity_transition():
    css = (REPO / "web/css/panels/grid.css").read_text(encoding="utf-8")
    bodies = _rule_bodies(css, ".mm-zoi-canvas")
    # Anchor: the rule is still there (the overlay canvas uses its
    # pointer-events / z-index), so an empty match cannot pass.
    assert len(bodies) == 1, bodies
    body = bodies[0]
    assert "pointer-events: none" in body, body
    assert "z-index: 2" in body, body
    assert "opacity" not in body, body
    assert "transition" not in body, body


def test_no_stylesheet_hides_the_zoi_canvas_by_opacity():
    hits = []
    for p in sorted((REPO / "web/css").rglob("*.css")):
        text = p.read_text(encoding="utf-8")
        for sel in (".mm-zoi-canvas", "#am-zoi-canvas"):
            for body in _rule_bodies(text, sel):
                if re.search(r"(^|[;\s{])opacity\s*:\s*0(\.0*)?\s*[;}]?",
                             body):
                    hits.append((p.relative_to(REPO).as_posix(), sel))
    assert hits == [], hits


def test_the_zoi_comments_name_the_real_cause():
    text = (REPO / "web/js/panels/minimap_zoi.js").read_text(
        encoding="utf-8")
    # The inline pin stays (belt and braces) ...
    assert 'canvas.style.opacity = "1";' in text
    # ... but no comment still calls the cause an unexplained quirk.
    assert "No CSS/JS rule set it" not in text
    assert "most likely a Chromium quirk" not in text
    assert "S144-U-259" in text


_READ = r"""(inject) => {
  const c = document.getElementById('am-zoi-canvas');
  if (!c) return {err: 'no #am-zoi-canvas'};
  const pinned = c.style.opacity;
  // Read the stylesheet's transition before touching anything, then
  // suspend transitions inline: a running opacity transition would make
  // getComputedStyle report its START value, not the rule's own value.
  const tdur = getComputedStyle(c).transitionDuration;
  c.style.transition = 'none';
  c.style.removeProperty('opacity');
  let st = null;
  if (inject) {
    st = document.createElement('style');
    st.textContent = '.mm-zoi-canvas { opacity: 0.25; }';
    document.head.appendChild(st);
  }
  const cs = getComputedStyle(c);
  const out = {
    pinned,
    inline: c.style.opacity,
    cls: c.classList.contains('mm-zoi-canvas'),
    opacity: cs.opacity,
    tdur,
    pe: cs.pointerEvents,
    bg: cs.backgroundColor,
    boxRects: c.parentElement ? c.parentElement.getClientRects().length : -1,
    width: c.width,
  };
  if (st) st.remove();
  c.style.removeProperty('transition');
  return out;
}"""

_ZOI_STATE = {
    "mode_key": "sr",
    "coach": {"action": "Push mid", "immediate": "Group up", "kda": "1/0/0"},
    "liveclient": {"level": 6, "game_time_s": 120},
    "minimap_rect": {"x": 1600, "y": 761, "w": 312, "h": 312, "flip": False,
                     "source": "settings", "native_w": 2560,
                     "native_h": 1440},
    "zoi": {
        "bubbles": [
            {"team": "blue", "cx": 0.2, "cy": 0.8, "r_frac": 0.12,
             "weight": 60},
            {"team": "red", "cx": 0.75, "cy": 0.25, "r_frac": 0.11,
             "weight": 50},
        ],
        "demarcation": {"x1": 0.0, "y1": 0.35, "x2": 1.0, "y2": 0.65,
                        "ally_side": "bottom"},
    },
}


def _probe(mock_server, pw_browser, query, data, wait_js, inject):
    mock_server._store["data"] = data
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/" + query,
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(wait_js, timeout=10_000)
        got = page.evaluate(_READ, inject)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    assert got["cls"] is True, got
    assert got["inline"] == "", got
    return got


_SHELLS = {
    # Overlay shell before any ZOI paint: no envelope, so the inline pin
    # was never written.
    "overlay-unpainted": (
        "?ui_mock=1&mode=sr&overlay=1", {},
        "() => document.body.dataset.shell === 'overlay'"
        " && !!document.getElementById('am-zoi-canvas')"),
    # Overlay shell after a live ZOI paint: the pin was written, then the
    # probe strips it, so the read is the stylesheet's answer.
    "overlay-painted": (
        "?overlay=1&mode=sr", _ZOI_STATE,
        "() => { const c = document.getElementById('am-zoi-canvas');"
        " return !!c && c.width > 0 && c.style.opacity === '1'; }"),
    # Dashboard shell (the canvas is served there too, inside a hidden box).
    "dashboard": (
        "?ui_mock=1&mode=sr#active-match", {},
        "() => document.body.dataset.view === 'active-match'"),
}


@pytest.mark.parametrize("shell", sorted(_SHELLS))
def test_the_zoi_canvas_is_opaque_without_its_inline_pin(
        mock_server, pw_browser, shell):
    query, data, wait_js = _SHELLS[shell]
    got = _probe(mock_server, pw_browser, query, data, wait_js, False)
    if shell == "overlay-painted":
        # Anchor: this case really painted and wrote the pin first.
        assert got["pinned"] == "1" and got["width"] > 0, got
    assert got["opacity"] == "1", got
    assert got["tdur"] == "0s", got
    assert got["pe"] == "none", got
    # An opaque canvas that has not painted shows nothing: no background.
    assert got["bg"] == "rgba(0, 0, 0, 0)", got
    if shell == "dashboard":
        # The dashboard never lays out the minimap box, so the change is
        # invisible there.
        assert got["boxRects"] == 0, got
    if shell == "overlay-painted":
        assert got["boxRects"] == 1, got


def test_counter_control_the_probe_sees_a_class_opacity_rule(
        mock_server, pw_browser):
    query, data, wait_js = _SHELLS["overlay-unpainted"]
    got = _probe(mock_server, pw_browser, query, data, wait_js, True)
    assert got["opacity"] == "0.25", got
