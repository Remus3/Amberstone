"""
tests/snapshot_panels/test_overlay_league_text_contrast.py
S144-U-299 (s144 uiux): EVERY text line of every League overlay widget shown
under ?ui_mock=1&mode=<sr|aram|mayhem|arena>&overlay=1 - w-call, w-build,
w-ovds and w-launcher - reaches the WCAG 1.4.3 AA text floor (4.5:1) on its
own backing in all six themes, over any game pixel, both while the widget is
live and in the idle recede. SVG text counts as text and is read by its
FILL, not its color.

WHY. The League overlay contrast pins each read ONE element (S144-U-275 call
glyph, U-278 hotkey hints, U-279 empty caption, U-281 build delta, U-288
objective footer, the lead bar). The TFT widgets got a whole-widget sweep in
S144-U-298; nothing swept the League widgets, so a line no pin names could
sit under the floor unseen.

THE DEFECT the sweep found. The threat donut placeholder sigil ("?" for no
damage mix, "." while fetching; web/js/panels/threat_donut.js _placeholder)
is SVG text painted with the literal fill="#888", inside the 0.85 opacity
.threat-donut-empty wrap. In the w-build THREATS strip (five tiles in SR,
ARAM and Mayhem, ten in Arena) it read 3.53:1 live and 2.90:1 idle (arcane),
4.04 / 3.20 at best (terminal): under the 4.5:1 text floor, and in five of
six themes under even the 3:1 graphics floor when idle. Every other line held
4.65:1 or more idle. A color-based read of the same text reported the
inherited 0.94-lightness ink and passed it, which is why the fill is read.

THE FIX. The sigil carries class threat-donut-sigil and fill="currentColor"
(no colour literal; the fallback is the row's own ink); active_match.css
paints it --text-dim on the dashboard, and the overlay palette re-points it
to rgba(--ovx-text, 0.75) (doctrine section 5: no colour outside the --ovx-*
table reaches an overlay widget). After: see the QA ledger, S144-U-299.

Contrast pair (the S144-U-275 / U-278 / U-288 method): the ink, with every
opacity inside the widget folded in, over the backgrounds of the line and of
every ancestor up to its widget WHOSE BOX CONTAINS THE LINE, then the widget
opacity, over a game pixel G in {0, 64, 128, 192, 255}, against the same
chain without the ink. The one aria-hidden glyph (the call band glyph) is a
graphical object ruled at 3:1 by S144-U-275; the sweep holds it there and
asserts it is the only aria-hidden line, so no text can hide behind the
exemption. No line is 18.66 px or larger, so 4.5:1 binds every other one.
S144-U-301 (s144 uiux cycle 293) extends the sweep to the w-call objective
respawn chips, which ?ui_mock=1 never paints: a synthetic live SR envelope
(every chip pending, then every chip up), six themes, live and idle. The chips
painted a 0.15 / 0.18 tint of their hue that LIGHTENED the call pane under the
ink: 3.62:1 (DRAKE, arcane) to 4.72:1 idle, every state under AA in five of
six themes. They now sit on the --ovx-bg-nested 0.9 inset-row backing: 6.21:1
live, 4.71:1 idle worst. The bare 0.58 frame under w-stats, w-nextbuy and
w-objgauges is the DS3 see-through question (operator-gated), not swept here.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_overlay_hotkey_hint_contrast import _worst

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_MODES = ["sr", "aram", "mayhem", "arena"]
_AA = 4.5
_GRAPHIC = 3.0
_LARGE = 18.66
_SHEET = "*, *::before, *::after { transition: none !important; }"
_WIDGETS = {"w-build", "w-call", "w-launcher", "w-ovds"}

# One synchronous read per idle state: every visible widget, every visible
# element holding a text node (SVG text by its fill and fill-opacity).
_READ = """(idle) => {
""" + _HELPERS + """
  const body = document.body;
  body.setAttribute('data-rc-idle', idle ? '1' : '0');
  const inside = (o, i) => i.left >= o.left - 0.5 && i.right <= o.right + 0.5
    && i.top >= o.top - 0.5 && i.bottom <= o.bottom + 0.5;
  const out = {};
  for (const w of document.querySelectorAll('.ovx-widget')) {
    if (!w.checkVisibility()) continue;
    let wop = 1;
    for (let n = w; n; n = n.parentElement) {
      wop *= parseFloat(getComputedStyle(n).opacity);
    }
    const lines = [];
    for (const h of w.querySelectorAll('*')) {
      if (![...h.childNodes].some(
          n => n.nodeType === 3 && n.textContent.trim())) continue;
      if (!h.checkVisibility()) continue;
      const hb = h.getBoundingClientRect();
      if (hb.width < 1 || hb.height < 1) continue;
      const layers = [];
      let inner = 1;
      for (let n = h; n; n = n.parentElement) {
        const cs = getComputedStyle(n);
        const b = rgba(cs.backgroundColor);
        if (b[3] > 0 && inside(n.getBoundingClientRect(), hb)) layers.push(b);
        if (n === w) break;
        inner *= parseFloat(cs.opacity);
      }
      const cs = getComputedStyle(h);
      const svg = h instanceof SVGElement;
      const color = rgba(svg ? cs.fill : cs.color);
      if (svg) color[3] *= parseFloat(cs.fillOpacity);
      const cls = svg ? h.getAttribute('class') || '' : h.className;
      lines.push({cls: cls, svg: svg, text: h.textContent.trim().slice(0, 28),
                  aria: !!h.closest('[aria-hidden="true"]'),
                  fillAttr: h.getAttribute('fill'),
                  color: color, inner: inner, layers: layers, wop: wop,
                  size: parseFloat(cs.fontSize)});
    }
    out[w.dataset.ovxId || w.id] = lines;
  }
  return out;
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, mode):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url
                  + f"/?ui_mock=1&mode={mode}&overlay=1&theme={theme}",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'", timeout=10_000)
        page.wait_for_selector(
            '.ovx-widget[data-ovx-id="w-call"] #am-call-body > div',
            state="visible", timeout=10_000)
        # The THREATS strip settles to its "?" tiles once every damage-mix
        # fetch has failed (the mock serves none): wait until no tile is
        # still loading and at least one sigil is up.
        page.wait_for_function(
            "() => { const b = document.querySelector("
            "'.ovx-widget[data-ovx-id=\"w-build\"]');"
            " return !!b && !b.querySelector('.threat-donut-loading')"
            " && !!b.querySelector('.threat-donut-empty text'); }",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = {"live": page.evaluate(_READ, 0),
               "idle": page.evaluate(_READ, 1)}
        got["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, mode):
    key = (theme, mode)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode)
    return measured[key]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_league_overlay_line_reaches_aa_live_and_idle(
        theme, mode, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    low = []
    for state in ("live", "idle"):
        widgets = got[state]
        # Anchor: a widget that failed to show would pass the loop.
        assert _WIDGETS <= set(widgets), (state, sorted(widgets))
        for wid in _WIDGETS:
            assert widgets[wid], f"{state}: {wid} read no text"
        aria = set()
        for wid, lines in widgets.items():
            for ln in lines:
                assert ln["size"] < _LARGE, (wid, ln["cls"], ln["size"])
                floor = _AA
                if ln["aria"]:
                    aria.add((wid, ln["cls"]))
                    floor = _GRAPHIC
                ratio = _worst(ln)
                if ratio < floor:
                    low.append((state, wid, ln["cls"], ln["text"],
                                round(ratio, 2), ln["color"]))
        # The 3:1 exemption covers the call band glyph and nothing else.
        assert aria <= {("w-call", "am-call-glyph")}, (state, aria)
    assert not low, f"{theme} {mode}: {low}"


@pytest.mark.parametrize("mode", _MODES)
def test_the_sweep_reads_the_threat_sigils_by_fill(
        mode, measured, mock_server, pw_browser):
    # The sigils are the lines a color-based read passed: pin that the sweep
    # sees them as SVG text, one per enemy (five, ten in Arena's lobby), and
    # that the recede is real so the idle pair is honest.
    got = _get(measured, mock_server, pw_browser, "arcane", mode)
    live = [ln for ln in got["live"]["w-build"] if ln["svg"]]
    idle = [ln for ln in got["idle"]["w-build"] if ln["svg"]]
    want = 10 if mode == "arena" else 5
    assert len(live) == want, live
    for ln in live:
        assert ln["text"] == "?", ln
        assert ln["cls"] == "threat-donut-sigil", ln
        assert ln["layers"], ln
        assert ln["wop"] == 1.0, ln
    assert idle and all(0 < ln["wop"] < 1.0 for ln in idle), idle


@pytest.mark.parametrize("theme", ["hextech", "arcane"])
def test_the_sigil_stays_a_quiet_neutral_on_the_overlay_palette(
        theme, measured, mock_server, pw_browser):
    # Hierarchy and palette law: the placeholder is neutral overlay ink
    # (--ovx-text parts), at or under the 0.75 body-ink tier and above the
    # 0.62 footer tier, and carries no colour literal of its own.
    got = _get(measured, mock_server, pw_browser, theme, "sr")
    sig = [ln for ln in got["live"]["w-build"] if ln["svg"]]
    assert sig, got["live"]["w-build"]
    for ln in sig:
        assert ln["fillAttr"] == "currentColor", ln
        assert ln["color"][:3] == [255, 255, 255], ln["color"]
        assert 0.62 <= ln["color"][3] <= 0.75, ln["color"]


# Dashboard Active Match THREATS strip: the same sigil on the page canvas.
_DASH_READ = """() => {
""" + _HELPERS + """
  const out = [];
  for (const h of document.querySelectorAll(
      '#view-active-match .threat-donut-empty text')) {
    if (!h.checkVisibility()) continue;
    const hb = h.getBoundingClientRect();
    const inside = (o) => hb.left >= o.left - 0.5 && hb.right <= o.right + 0.5
      && hb.top >= o.top - 0.5 && hb.bottom <= o.bottom + 0.5;
    const layers = [];
    let inner = 1;
    for (let n = h; n; n = n.parentElement) {
      const cs = getComputedStyle(n);
      const b = rgba(cs.backgroundColor);
      if (b[3] > 0 && inside(n.getBoundingClientRect())) layers.push(b);
      inner *= parseFloat(cs.opacity);
    }
    const cs = getComputedStyle(h);
    const color = rgba(cs.fill);
    color[3] *= parseFloat(cs.fillOpacity);
    out.push({text: h.textContent.trim(), color: color, inner: inner,
              layers: layers, wop: 1, opaque: layers.some(l => l[3] >= 1)});
  }
  return out;
}"""


@pytest.mark.parametrize("theme", _THEMES)
def test_the_dashboard_threat_sigil_reaches_aa(theme, mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}"
                  "#active-match", wait_until="domcontentloaded",
                  timeout=15_000)
        page.wait_for_function(
            "() => { const v = document.getElementById('view-active-match');"
            " return !!v && !v.querySelector('.threat-donut-loading')"
            " && !!v.querySelector('.threat-donut-empty text'); }",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_DASH_READ)
        booted = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert booted == theme, f"booted on {booted}, not {theme}"
    assert len(got) == 5, got
    low = []
    for ln in got:
        # The page canvas is opaque, so the game pixel cannot matter.
        assert ln["opaque"], ln
        ratio = _worst(ln)
        if ratio < _AA:
            low.append((ln["text"], round(ratio, 2), ln["color"]))
    assert not low, f"{theme}: {low}"


# S144-U-301: the w-call objective respawn chips (web/js/panels/
# objective_chips.js, "BARON 4:20 / DRAKE UP") paint only on a live envelope
# whose liveclient carries game_time_s and objective_events; the ui_mock
# fixture carries neither, so the sweep above never saw them. Two synthetic
# live SR envelopes at 15:00 (game_time_s 900): every chip pending, and every
# chip up. Event shape: dashboard/_liveclient.py objective_events.
_CHIP_CLOCK = 900
_CHIP_EVENTS = {
    "pending": [
        {"name": "baron", "killer_team": "ally", "down_at_s": 800},
        {"name": "dragon", "killer_team": "ally", "down_at_s": 700,
         "dragon_type": "Fire"},
        {"name": "herald", "killer_team": "enemy", "down_at_s": 700},
    ],
    "up": [
        {"name": "baron", "killer_team": "ally", "down_at_s": 100},
        {"name": "dragon", "killer_team": "ally", "down_at_s": 100,
         "dragon_type": "Fire"},
        {"name": "herald", "killer_team": "enemy", "down_at_s": 100},
    ],
}
# OBJ_CYCLE baron 360 / dragon 300 / herald 360, OBJ_ORDER baron, dragon,
# herald; ETA = down_at_s + cycle - game_time_s.
_CHIP_TEXT = {
    "pending": ["BARON", "4:20", "DRAKE", "1:40", "HERALD", "2:40"],
    "up": ["BARON", "UP", "DRAKE", "UP", "HERALD", "UP"],
}
# The ink each chip keeps (overlay.css re-points the --signal-* tokens to
# the --ovx-* palette): the hue still tells the three apart, and an up chip
# is the good green whatever the objective.
_CHIP_INK = {
    "pending": [[10, 200, 185, 1], [200, 170, 110, 1], [255, 255, 255, 0.55]],
    "up": [[55, 208, 138, 1]] * 3,
}


def _chip_env(state):
    return {
        "mode_key": "sr",
        "lcu": {"phase": "InProgress"},
        "coach": {"action": "Push mid", "immediate": "Group up",
                  "kda": "1/0/0"},
        "liveclient": {"level": 11, "game_time_s": _CHIP_CLOCK,
                       "objective_events": _CHIP_EVENTS[state]},
    }


@pytest.fixture(scope="module")
def chips_measured():
    return {}


def _measure_chips(mock_server, pw_browser, theme, state):
    mock_server._store["data"] = _chip_env(state)
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/?overlay=1&mode=sr&theme={theme}",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'", timeout=10_000)
        page.wait_for_function(
            "(want) => { const m = document.getElementById('am-obj-chips');"
            " return !!m && !m.hidden && [...m.querySelectorAll("
            "'.obj-label, .obj-eta')].map(e => e.textContent).join('|')"
            " === want; }",
            arg="|".join(_CHIP_TEXT[state]), timeout=10_000)
        page.add_style_tag(content=_SHEET)
        got = {"live": page.evaluate(_READ, 0),
               "idle": page.evaluate(_READ, 1)}
        got["theme"] = page.evaluate(
            "() => document.documentElement.dataset.theme || 'hextech'")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get_chips(chips_measured, mock_server, pw_browser, theme, state):
    key = (theme, state)
    if key not in chips_measured:
        chips_measured[key] = _measure_chips(
            mock_server, pw_browser, theme, state)
    return chips_measured[key]


def _chip_lines(lines):
    return [ln for ln in lines if ln["cls"] in ("obj-label", "obj-eta")]


@pytest.mark.parametrize("state", ["pending", "up"])
@pytest.mark.parametrize("theme", _THEMES)
def test_the_call_objective_chips_reach_aa_live_and_idle(
        theme, state, chips_measured, mock_server, pw_browser):
    got = _get_chips(chips_measured, mock_server, pw_browser, theme, state)
    low = []
    for mode in ("live", "idle"):
        lines = got[mode].get("w-call", [])
        chips = _chip_lines(lines)
        # Anchor: the six chip lines, in render order, or the loop is empty.
        assert [ln["text"] for ln in chips] == _CHIP_TEXT[state], (mode, chips)
        if mode == "idle":
            assert all(0 < ln["wop"] < 1.0 for ln in chips), chips
        for ln in lines:
            assert ln["size"] < _LARGE, (ln["cls"], ln["size"])
            floor = _GRAPHIC if ln["aria"] else _AA
            if ln["aria"]:
                assert ln["cls"] == "am-call-glyph", ln
            ratio = _worst(ln)
            if ratio < floor:
                low.append((mode, ln["cls"], ln["text"], round(ratio, 2),
                            ln["color"], ln["layers"][:1]))
    assert not low, f"{theme} {state}: {low}"


@pytest.mark.parametrize("state", ["pending", "up"])
def test_the_chips_sit_on_the_nested_overlay_backing_and_keep_their_hue(
        state, chips_measured, mock_server, pw_browser):
    # Palette law (doctrine section 5): the chip backing is the inset-row
    # --ovx-bg-nested at 0.9 every widget row uses, not a tint literal, and
    # the hue rides the ink (and the border), one per objective.
    got = _get_chips(chips_measured, mock_server, pw_browser, "arcane", state)
    chips = _chip_lines(got["live"]["w-call"])
    assert len(chips) == 6, chips
    for i, ln in enumerate(chips):
        back = ln["layers"][0]
        assert back[:3] == [10, 14, 20], ln
        assert abs(back[3] - 0.9) < 0.01, ln
        want = _CHIP_INK[state][i // 2]
        assert ln["color"][:3] == want[:3], ln
        assert abs(ln["color"][3] - want[3]) < 0.01, ln
