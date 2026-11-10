"""
tests/snapshot_panels/test_tft_last_match_baseline_contrast.py
S144-U-293 (s144 uiux): the TFT Post Game Review card reads whole and at
the WCAG 1.4.3 AA text floor (4.5:1) in all six themes at the 1920x920
baseline (1920x1080 with Chrome chrome).

WHY. tests/snapshot_panels/test_tft_last_match_view.py (RM-952) pins the
card's text, its 16 px floor and its horizontal overflow, but only at a
1920x1080 viewport and only in the default theme. Nothing pinned its
contrast in any theme, or that the whole card - the Lobby list is its last
section - fits the 920 px tall usable viewport.

MEASURED headless under /?ui_mock=1&mode=tft&theme=<t>#last-match
(web/data/ui_mock/last_match_tft.json, the real RC payload with its game id
blanked), ancestor opacity folded in, no defect found. The lowest-contrast
text in every theme is the .lm-tft-note line ("Not recorded ..."): 4.88
hextech, 4.92 arcane, 4.98 ember, 5.10 bloodmoon, 5.11 moonlit, 5.35
terminal. The next lowest, .lm-tft-fact-label, reads 6.37 or more. The last
lobby row ends at y=907 of 920; no text box is clipped horizontally.

Checked per theme: the page booted on that theme; every visible text node
in #lm-tft resolves an opaque surface and reaches 4.5:1; no block-level
text box is cut horizontally (an inline box always reads scrollWidth ==
clientWidth, so it is left out); the last lobby row and the last section heading end
inside the viewport; the page does not scroll horizontally.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_AA = 4.5
_VP = {"width": 1920, "height": 920}
_SHEET = "*, *::before, *::after { transition: none !important; }"

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
  const host = document.getElementById('lm-tft');
  const lines = [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map((e) => {
      const c = rgba(getComputedStyle(e).color);
      c[3] *= alpha(e);
      const s = surface(e);
      return {cls: e.className || e.tagName,
              text: e.textContent.trim().slice(0, 40),
              fg: s ? over(c, s) : null, bg: s,
              inline: getComputedStyle(e).display === 'inline',
              cut: e.scrollWidth - e.clientWidth};
    });
  const rows = host.querySelectorAll('.lm-tft-lobby > li');
  const heads = host.querySelectorAll('.lm-tft-section h3');
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    lines,
    lobbyRows: rows.length,
    lastRowBottom: rows.length
      ? rows[rows.length - 1].getBoundingClientRect().bottom : null,
    lastHead: heads.length ? heads[heads.length - 1].textContent.trim() : null,
    lastHeadBottom: heads.length
      ? heads[heads.length - 1].getBoundingClientRect().bottom : null,
    vh: window.innerHeight,
    pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=_VP)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode=tft&theme={theme}#last-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "(() => { const h = document.getElementById('lm-tft');"
            " return !!(h && !h.hidden && h.querySelector('.lm-tft-place')"
            " && h.querySelector('.lm-tft-lobby > li')); })()",
            timeout=10_000,
        )
        page.add_style_tag(content=_SHEET)
        got = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


def _get(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", _THEMES)
def test_tft_pgr_text_reaches_aa_in_every_theme(
        measured, mock_server, pw_browser, theme):
    got = _get(measured, mock_server, pw_browser, theme)
    assert got["theme"] == theme, f"booted on {got['theme']}, not {theme}"
    # Anchor: an empty read would pass the loop below.
    assert len(got["lines"]) >= 40, len(got["lines"])
    notes = [ln for ln in got["lines"] if ln["cls"] == "lm-tft-note"]
    assert len(notes) == 2, notes
    low = []
    for ln in got["lines"]:
        assert ln["fg"] and ln["bg"], f"no opaque surface under {ln}"
        r = _ratio(ln["fg"], ln["bg"])
        if r < _AA:
            low.append((ln["cls"], ln["text"], round(r, 2)))
    assert not low, (theme, low)


@pytest.mark.parametrize("theme", _THEMES)
def test_tft_pgr_reads_whole_at_the_920_baseline(
        measured, mock_server, pw_browser, theme):
    got = _get(measured, mock_server, pw_browser, theme)
    assert got["vh"] == _VP["height"]
    # scrollWidth - clientWidth is 0 for an inline box whatever it holds,
    # so only block-level text boxes can show a cut; anchor that they exist.
    boxes = [ln for ln in got["lines"] if not ln["inline"]]
    assert len(boxes) >= 40, len(boxes)
    cut = [(ln["cls"], ln["text"], ln["cut"]) for ln in boxes if ln["cut"] > 0]
    assert not cut, (theme, cut)
    assert got["lobbyRows"] == 8
    assert got["lastHead"] == "Lobby"
    assert got["lastHeadBottom"] <= got["vh"], got["lastHeadBottom"]
    assert got["lastRowBottom"] <= got["vh"], (
        f"{theme}: the last lobby row ends at {got['lastRowBottom']}, "
        f"below the {got['vh']} px baseline")
    assert got["pageOverflow"] <= 0, got["pageOverflow"]
