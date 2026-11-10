"""
tests/snapshot_panels/test_tft_active_match_theme_contrast.py
S144-U-295 (s144 uiux): the TFT Active Match view reads whole and at the
WCAG 1.4.3 AA text floor (4.5:1) in all six themes at the 1920x920
baseline (1920x1080 with Chrome chrome), on all three TFT fixtures, and its
lobby HP bars reach the WCAG 1.4.11 non-text floor (3:1) in both fill
states.

WHY. The TFT Active Match pins (test_tft_active_match_view,
test_tft_ui_mock_active_match, test_tft_board_*, test_tft_lobby_row_fits,
test_tft_stat_strip_reflow) cover its text, geometry and reflow, but only
in the default theme. The six-theme contrast pins on this view
(test_am_call_eyebrow_contrast, test_am_empty_line_contrast,
test_am_map_roster_state_contrast) cover the SR / ARAM parts, not the TFT
board, lobby or stat strip. Nothing pinned the TFT branch in any theme but
hextech, and the lobby's low-HP fill (.am-tft-lob-fill.is-low) is in no
fixture at all: every recorded lobby row is above the low line.

MEASURED headless under /?ui_mock=1&mode=<m>&theme=<t>#active-match
(web/data/ui_mock/active_match_tft.json, active_match_tft_live.json,
active_match_tft_round.json), ancestor opacity folded in. Text: no defect.
Every visible text node reaches 4.5:1 in every theme on every fixture
(17 text boxes on tft / tft_live, 60 on tft_round), no block-level text
box is cut at 1920x920 and the page does not scroll sideways.

THE DEFECT. The lobby HP bar's track was --border-soft, a light veil over
the pane (web/css/panels/active_match.css .am-tft-lob-bar). The crit-band
red fill (.is-low, tftHpBand(hp) === "crit", active_match.js
_amTftLobbyNode) read 2.80:1 against that track in moonlit and arcane,
under the 3:1 floor, and only 3.29 (ember, bloodmoon) to 3.60 (terminal)
elsewhere. The bar is a graphical object that repeats the HP number beside
it, so the floor is 3:1 (the S144-U-277 ruling for state bars).

THE FIX. The track is --canvas, the page's deepest ground, defined in all
six themes: a sunken well. After: the red fill reads 4.88:1 (hextech) to
5.64:1 (terminal) against the track, the green 8.31:1 to 9.79:1; against
the pane the fills are unchanged (red 3.89 to 5.02, green 6.72 to 8.24),
and the empty track still differs from the pane (1.12:1 to 1.27:1, was
1.18 to 1.40), so the bar's full extent stays visible.

Not pinned here, by design: at the 721-800 px three-pane band the board
eyebrow, the lobby eyebrow and a long unit name ("Fiddlesticks") ellipsise.
That is the RM-1766 / RM-1767 contract (the eyebrow's title and the chip's
title / aria-label carry the whole text), pinned by test_tft_board_more_cue
and test_tft_board_unit_columns.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_MODES = ["tft", "tft_live", "tft_round"]
_AA = 4.5
_NON_TEXT = 3.0
_VP = {"width": 1920, "height": 920}
_SHEET = ("*, *::before, *::after { transition: none !important;"
          " animation: none !important; }")

# Anchors: an empty read would pass every loop below. Counts observed on
# the fixtures; a floor, so a new line does not fail the pin.
_MIN_LINES = {"tft": 15, "tft_live": 15, "tft_round": 55}

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const alpha = (el) => {
    let a = 1;
    for (let n = el; n; n = n.parentElement) {
      a *= parseFloat(getComputedStyle(n).opacity);
    }
    return a;
  };
  const host = document.getElementById('view-active-match');
  const lines = [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map((e) => {
      const c = rgba(getComputedStyle(e).color);
      c[3] *= alpha(e);
      const s = surface(e);
      return {cls: (typeof e.className === 'string' && e.className)
                   || e.tagName,
              text: e.textContent.trim().slice(0, 40),
              fg: s ? over(c, s) : null, bg: s,
              inline: getComputedStyle(e).display === 'inline',
              cut: e.scrollWidth - e.clientWidth};
    });
  // Lobby HP bars, in both fill states: the recorded rows are all above
  // the low line, so the low fill is set on a copy of the first row.
  const bars = [];
  const row = host.querySelector('.am-tft-lob-row');
  if (row && row.querySelector('.am-tft-lob-bar')) {
    const low = row.cloneNode(true);
    low.querySelector('.am-tft-lob-fill').classList.add('is-low');
    row.after(low);
    for (const r of [row, low]) {
      const bar = r.querySelector('.am-tft-lob-bar');
      const fill = r.querySelector('.am-tft-lob-fill');
      const s = surface(r);
      const t = s ? over(rgba(getComputedStyle(bar).backgroundColor), s)
                  : null;
      // The fill is painted inside the track, so it composites over the
      // track over the pane (exact even if a fill token turns translucent).
      bars.push({low: fill.classList.contains('is-low'),
                 visible: bar.checkVisibility(),
                 fillW: fill.getBoundingClientRect().width,
                 fill: t ? over(rgba(getComputedStyle(fill).backgroundColor), t)
                         : null,
                 track: t, bg: s});
    }
    low.remove();
  }
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    lines,
    stats: host.querySelectorAll('#am-call-body .am-tft-stat').length,
    units: host.querySelectorAll('.am-tft-unit').length,
    lobbyRows: host.querySelectorAll('.am-tft-lob-row').length,
    bars,
    vh: window.innerHeight,
    pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, mode):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport=_VP)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    # Deterministic: no live minimap crop and no vision answer.
    page.route("**/api/minimap-crop*",
               lambda r: r.fulfill(status=404, body=""))
    page.route("**/api/vision-state*", lambda r: r.fulfill(
        status=503, content_type="application/json", body="{}"))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode={mode}&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'"
            " && document.querySelectorAll("
            "'#am-call-body .am-tft-stats .am-tft-stat').length === 4",
            timeout=10_000,
        )
        if mode == "tft_round":
            page.wait_for_function(
                "() => document.querySelectorAll("
                "'#view-active-match .am-tft-lob-row').length === 8"
                " && document.querySelectorAll("
                "'#view-active-match .am-tft-unit').length === 7",
                timeout=10_000,
            )
        page.add_style_tag(content=_SHEET)
        page.evaluate("() => new Promise((r) => requestAnimationFrame("
                      "() => requestAnimationFrame(() => r())))")
        got = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


def _get(measured, mock_server, pw_browser, theme, mode):
    key = (theme, mode)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, mode)
    return measured[key]


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_tft_active_match_text_reaches_aa_in_every_theme(
        measured, mock_server, pw_browser, theme, mode):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    assert len(got["lines"]) >= _MIN_LINES[mode], len(got["lines"])
    assert got["stats"] == 4, got["stats"]
    if mode == "tft_round":
        assert (got["units"], got["lobbyRows"]) == (7, 8), (
            got["units"], got["lobbyRows"])
    low = []
    for ln in got["lines"]:
        assert ln["fg"] and ln["bg"], f"no opaque surface under {ln}"
        r = _ratio(ln["fg"], ln["bg"])
        if r < _AA:
            low.append((ln["cls"], ln["text"], round(r, 2)))
    assert not low, (theme, mode, low)


@pytest.mark.parametrize("mode", _MODES)
@pytest.mark.parametrize("theme", _THEMES)
def test_tft_active_match_reads_whole_at_the_920_baseline(
        measured, mock_server, pw_browser, theme, mode):
    got = _get(measured, mock_server, pw_browser, theme, mode)
    assert got["vh"] == _VP["height"]
    # scrollWidth - clientWidth is 0 for an inline box whatever it holds,
    # so only block-level text boxes can show a cut; anchor that they exist.
    boxes = [ln for ln in got["lines"] if not ln["inline"]]
    assert len(boxes) >= _MIN_LINES[mode] - 3, len(boxes)
    cut = [(ln["cls"], ln["text"], ln["cut"]) for ln in boxes if ln["cut"] > 0]
    assert not cut, (theme, mode, cut)
    assert got["pageOverflow"] <= 0, got["pageOverflow"]


@pytest.mark.parametrize("theme", _THEMES)
def test_tft_lobby_hp_bar_reaches_non_text_floor_in_every_theme(
        measured, mock_server, pw_browser, theme):
    got = _get(measured, mock_server, pw_browser, theme, "tft_round")
    bars = got["bars"]
    assert [b["low"] for b in bars] == [False, True], bars
    for b in bars:
        assert b["visible"] and b["fillW"] > 0, b
        assert b["fill"] and b["track"] and b["bg"], b
        # The fill must stand out from the empty track beside it and from
        # the row surface under the bar's rounded ends.
        vs_track = _ratio(b["fill"], b["track"])
        vs_bg = _ratio(b["fill"], b["bg"])
        assert vs_track >= _NON_TEXT, (theme, b["low"], round(vs_track, 2))
        assert vs_bg >= _NON_TEXT, (theme, b["low"], round(vs_bg, 2))
        # Control: the empty track is not the pane's own colour, so the
        # bar's full (100 HP) extent stays visible beside the fill.
        assert _ratio(b["track"], b["bg"]) > 1.05, (theme, b)
