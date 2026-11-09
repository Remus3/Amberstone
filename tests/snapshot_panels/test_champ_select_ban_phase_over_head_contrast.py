"""
tests/snapshot_panels/test_champ_select_ban_phase_over_head_contrast.py
S144-U-235 (s144 uiux): the champ-select Pick & Ban card's collapsed BAN
head ("BAN - phase over", .csv-pb168-bans.is-collapsed .csv-pb168-head,
web/js/panels/champ_select.js _csvRenderPickBan, styled in
web/css/panels/champ_select_view.css) reaches WCAG AA on its resolved
surface in all six themes, and stays the dimmest of the card's three
section heads.

MEASURED headless under /?ui_mock=1&mode=sr#champ-select at 1920x1080
before the fix (the SR fixture's active_round is a pick, so
_csvBanPhaseComplete collapses the ban section, RC2 E4). The head is
16 px / 700, so NOT WCAG large text and the 4.5:1 floor applies. It
painted --text-faint INSIDE a section at opacity 0.6, so its effective
colour is --text-faint at 60 percent over the card surface: about 2.6:1.
No documented exception covers it: the RC2 E4 comment asks only that the
head row "stays ... so the section is still labelled", and this program
already rejected dimming a label by opacity because it sinks text under
its floor (the S144 minimap stale-row ruling). Ruling: drop the section
opacity; the head keeps --text-faint (AA on --surface by its own
definition) and the accent dot alone carries the 0.6 fade, so the
collapsed head still reads dimmer than PICK and WHY THESE (--dim).

The browser resolves the colours; this test multiplies in every ancestor
opacity (the shared _HELPERS read() does not) and composites over the
stacked backgrounds, lane doc traps 3 and 4.
"""
import pytest

from tests.snapshot_panels.test_champ_select_view import _open_champ_select
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
# S144-U-241: the theme is flipped in-page, so every transition is off first
# (RM-1132); without it the reads straddle the swap in five themes.
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
  const head = (el) => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    const fg = rgba(cs.color);
    fg[3] *= alpha(el);
    const s = surface(el);
    return {text: el.textContent.trim(), fg: s ? over(fg, s) : null, bg: s,
            px: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
            visible: el.checkVisibility()};
  };
  const sect = document.querySelector(
    '#view-champ-select .csv-pb168-bans.is-collapsed');
  const row = sect && sect.querySelector('.csv-pb168-row');
  return {
    theme: document.documentElement.dataset.theme || 'hextech',
    collapsed: !!sect,
    rowShown: !!(row && row.checkVisibility()),
    ban: head(sect && sect.querySelector('.csv-pb168-head')),
    pick: head(document.querySelector(
      '#view-champ-select .csv-pb168-picks .csv-pb168-head')),
    why: head(document.querySelector(
      '#view-champ-select .csv-pb168-expl .csv-pb168-head')),
  };
}"""


def _measure(mock_server, pw_browser, theme):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "sr")
    try:
        page.add_style_tag(content=_SHEET)
        page.evaluate(
            "(t) => { document.documentElement.dataset.theme = t; }", theme)
        page.wait_for_function(
            "!!document.querySelector('#view-champ-select "
            ".csv-pb168-bans .csv-pb168-head')", timeout=10_000)
        got = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _got(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


@pytest.mark.parametrize("theme", _THEMES)
def test_collapsed_ban_head_reaches_aa(theme, measured, mock_server,
                                       pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    assert got["theme"] == theme, "theme did not apply"
    # Anchor: the fixture really collapsed the ban section (RC2 E4), the
    # cell row is out of layout and the head still labels the section.
    assert got["collapsed"], "ban section not collapsed under the SR mock"
    assert not got["rowShown"], "collapsed ban row still visible"
    ban = got["ban"]
    assert ban and ban["visible"], "collapsed BAN head not rendered"
    assert ban["text"] == "BAN - phase over", ban["text"]
    assert ban["px"] >= 16, f"head under the --fs-xs floor: {ban['px']}px"
    assert ban["fg"] and ban["bg"], "no resolved surface under the head"
    r = _ratio(ban["fg"], ban["bg"])
    assert r >= 4.5, (
        f"{theme}: 'BAN - phase over' ({ban['px']:g}px/{ban['weight']}) "
        f"{r:.2f}:1 < 4.5")


@pytest.mark.parametrize("theme", _THEMES)
def test_collapsed_ban_head_stays_the_dimmest_head(theme, measured,
                                                   mock_server, pw_browser):
    got = _got(measured, mock_server, pw_browser, theme)
    heads = {k: got[k] for k in ("ban", "pick", "why")}
    for k, h in heads.items():
        assert h and h["visible"] and h["fg"] and h["bg"], (
            f"{k} head not rendered")
        r = _ratio(h["fg"], h["bg"])
        assert r >= 4.5, f"{theme}: {h['text']!r} {r:.2f}:1 < 4.5"
    ban = _lum(heads["ban"]["fg"])
    for k in ("pick", "why"):
        assert ban < _lum(heads[k]["fg"]), (
            f"{theme}: the collapsed BAN head is not dimmer than "
            f"{heads[k]['text']!r}")
