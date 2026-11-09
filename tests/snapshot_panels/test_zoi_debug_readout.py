"""
tests/snapshot_panels/test_zoi_debug_readout.py
S144-U-245 (s144 uiux): the Active Match minimap's ?debug=1 zone-pressure
readout (#zoi-debug, "R=... baseline ... deadband ... self-pressure ...")
clears when the minimap loses your position, sits on the 16 px --fs-xs
floor, and reaches the WCAG 1.4.3 AA text floor (4.5:1) on its own
--surface-alt chip in all six themes, at the 1920x920 baseline and the
923x1280 companion window.

THE DEFECTS. MEASURED headless under /?ui_mock=1&mode=sr&debug=1
#active-match by driving web/js/panels/map_state.js
renderMinimapCanvases() with a value shape that puts you deep in enemy
pressure (three enemies stacked on your dot), then with one that drops
your position (the S144-U-244 payloads):
- STALE: S144-U-244's _clearZone() reset the header zone pill on every
  lost-position path but never touched the readout, so it stayed shown
  with the last "self-pressure -N.NN" while the pill read "-" - the two
  disagreed exactly when someone was debugging a zone call;
- TYPOGRAPHY: grid.css .zoi-debug was a hard-coded 11 px, under the
  --fs-xs 16 px floor, with no documented operator exception;
- CONTRAST: it painted --text-faint on --surface-alt, the pair
  base.css's own "4.88:1 on --surface" note does not cover (lane doc
  trap 4).

- UNREACHABLE: the node sat in the #minimap panel inside the top-level
  <main>, which header.css hides in every view and overlay.css hides in
  the overlay shell, so it never rendered at all.

THE FIX. index.html moves the node into the Active Match MAP pane, after
#am-map-body (whose innerHTML the map render replaces); map_state.js
_clearZone() also hides the readout and empties its text; the rule moves
from grid.css to active_match.css (#view-active-match .zoi-debug) on
var(--fs-xs) and --text-dim. The chip, its padding and its monospace face
stay.

Checked per theme and viewport: the readout is shown with a live SAFE
call's pressure first (so the reset checks cannot pass on a readout that never
lit), reaches 4.5:1 on its resolved surface, is --text-dim at
var(--fs-xs) and stays quieter than full --text on the same chip; and
each lost-position payload (dead, absent from the ally positions, no
positions, empty position maps) hides it and empties it.
"""
import re

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 920), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"
_LOST = ["dead", "absent", "nopos", "empty"]

# Paint a SAFE call through the real renderer (no style reads here): you on
# your own side with an ally beside you. A SAFE call, not the deep one, so
# the colour read below never shares the page with the enemy pill's zoneWarn
# pulse (header.css / map_state.css), which the RM-1132 audit flags. The
# deep payload is kept for the reset checks, which read no style.
_DRIVE = """async () => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/map_state.js'));
  if (!url) return {err: 'map_state.js not loaded'};
  const m = await import(url);
  window.__zoiDeep = {
    champion: 'Ahri', my_team: 'blue', game_time_s: 900,
    positions: {
      allies: {Ahri: {x: 0.80, y: 0.20}},
      enemies: {Zed: {x: 0.80, y: 0.20}, Lux: {x: 0.80, y: 0.21},
                Jinx: {x: 0.81, y: 0.20}},
    },
  };
  window.__zoiRender = m.renderMinimapCanvases;
  m.renderMinimapCanvases({
    champion: 'Ahri', my_team: 'blue', game_time_s: 900,
    positions: {allies: {Ahri: {x: 0.15, y: 0.85}, Garen: {x: 0.17, y: 0.83}},
                enemies: {}},
  });
  return {ok: true, zone: document.body.dataset.zone ?? null};
}"""

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const root = getComputedStyle(document.documentElement);
  const tok = (name) => rgba(root.getPropertyValue(name).trim());
  const el = document.getElementById('zoi-debug');
  if (!el) return {err: 'no #zoi-debug'};
  const cs = getComputedStyle(el);
  const s = surface(el);
  const fg = rgba(cs.color);
  return {theme: document.documentElement.dataset.theme || 'hextech',
          shown: el.checkVisibility(), text: el.textContent,
          color: fg, fg: s ? over(fg, s) : null, bg: s,
          full: s ? over(tok('--text'), s) : null,
          dim: tok('--text-dim'), opacity: parseFloat(cs.opacity),
          size: parseFloat(cs.fontSize),
          xs: parseFloat(root.getPropertyValue('--fs-xs'))};
}"""

# Each lost-position payload after a fresh deep call: is the readout gone?
_RESET = """() => {
  const deep = window.__zoiDeep;
  const lost = {
    dead: {...deep, ally_respawns: {Ahri: 12}},
    absent: {...deep, champion: 'Garen'},
    nopos: {champion: 'Ahri', my_team: 'blue', game_time_s: 900,
            positions: null},
    empty: {...deep, positions: {allies: {}, enemies: {}}},
  };
  const el = document.getElementById('zoi-debug');
  const out = {};
  for (const [k, p] of Object.entries(lost)) {
    window.__zoiRender(deep);
    const before = {shown: el.checkVisibility(), text: el.textContent};
    window.__zoiRender(p);
    out[k] = {before, after: {shown: el.checkVisibility(),
                              text: el.textContent,
                              hidden: el.classList.contains('hidden')}};
  }
  return out;
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode=sr&debug=1&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        drove = page.evaluate(_DRIVE)
        assert "err" not in drove, drove
        assert drove["zone"] == "safe", drove
        got = page.evaluate(_MEASURE)
        got["reset"] = page.evaluate(_RESET)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    return got


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


def _lum(c) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_readout_is_live_with_the_pressure(theme, vp, measured,
                                                mock_server, pw_browser):
    # Anchor: ?debug=1 really shows the readout with this call's numbers
    # (the SAFE call's pressure is positive).
    got = _get(measured, mock_server, pw_browser, theme, vp)
    assert got["shown"], got
    assert re.search(r"self-pressure \d+\.\d\d$", got["text"]), got["text"]


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_readout_reaches_aa_on_its_chip(theme, vp, measured,
                                            mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    assert got["bg"] is not None, got
    assert got["opacity"] == 1, got
    ratio = _ratio(got["fg"], got["bg"])
    assert ratio >= _AA, f"{theme} {vp}: {ratio:.2f}:1 under {_AA}"


@pytest.mark.parametrize("theme", _THEMES)
def test_the_readout_is_dim_text_on_the_type_floor(theme, measured,
                                                   mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    assert got["xs"] == 16.0, got["xs"]
    assert got["size"] == got["xs"], (theme, got["size"])
    assert got["color"] == got["dim"], (theme, got["color"], got["dim"])
    # A debug readout is never the loudest thing on the minimap.
    assert _lum(got["fg"]) < _lum(got["full"]), (theme, got)


@pytest.mark.parametrize("case", _LOST)
def test_a_lost_position_hides_and_empties_the_readout(case, measured,
                                                       mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, _THEMES[0], _VIEWPORTS[0])
    r = got["reset"][case]
    assert r["before"]["shown"], r
    assert "self-pressure" in r["before"]["text"], r
    assert not r["after"]["shown"], r
    assert r["after"]["hidden"], r
    assert r["after"]["text"] == "", r
