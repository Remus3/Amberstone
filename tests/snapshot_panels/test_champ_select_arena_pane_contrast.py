"""
tests/snapshot_panels/test_champ_select_arena_pane_contrast.py
RM-1197 (s144 uiux): the Arena champ-select centre pane
(web/js/panels/champ_select.js _csvArenaPaneHtml - the duo row, "My
augments" and the current-round "pick one" box) reaches WCAG AA on its
resolved surface on all six themes. Styled in
web/css/panels/champ_select_view.css.

MEASURED headless under /?ui_mock=1&mode=arena&theme=<t>#champ-select at
1920x1080 before the fix (colours resolved by the browser and composited
over the stacked backgrounds, lane doc traps 3 and 4):
  .csv-duo-cell-tag "ALLY" (11px bold, --text-faint on the --surface-2
    duo cell)                       4.31 to 4.48:1 on hextech, ember,
                                    moonlit, arcane (terminal 5.03,
                                    bloodmoon 4.52)
  .csv-augment-options .csv-augments-title "SILVER round . pick one"
    (--accent-2)                    3.39 to 3.75:1 on ember, bloodmoon,
                                    arcane, where --accent-2 is a deep
                                    red or violet, not the hextech teal
The tag now takes --text-dim (still dimmer than the champion name it
labels). The title keeps its accent hue, but the colour is now mixed
toward --text, so it stays tinted and clears AA on every theme. The 11px
tag size is a documented operator exception (item 178/181, pinned by
tests/test_csv_typography_v21_floor.py), so it is NOT changed here.

The empty partner slot (.csv-duo-cell.is-empty, opacity 0.55, "?" /
"ALLY" / "waiting...") is a deliberately dimmed placeholder for a slot
with no player in it; it is excluded from the AA floor, and the test pins
that it is the ONLY dimmed element, because the shared surface helper
ignores opacity.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _lum, _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]

_MEASURE = """async () => {
  await document.fonts.ready;
""" + _HELPERS + """
  const op = (e) => {
    let o = 1;
    for (let n = e; n; n = n.parentElement)
      o *= parseFloat(getComputedStyle(n).opacity);
    return o;
  };
  const out = [];
  const hosts = [['duo', '.csv-duo-row'], ['mine', '.csv-augments'],
                 ['pick', '.csv-augment-options']];
  for (const [state, sel] of hosts) {
    const host = document.querySelector('#view-champ-select ' + sel);
    if (!host) continue;
    for (const e of host.querySelectorAll('*')) {
      if (![...e.childNodes].some(
          (n) => n.nodeType === 3 && n.textContent.trim())) continue;
      if (!e.checkVisibility()) continue;
      const s = surface(e);
      out.push([state, e.className, e.textContent,
                s ? over(rgba(getComputedStyle(e).color), s) : null, s,
                op(e), !!e.closest('.csv-duo-cell.is-empty')]);
    }
  }
  return out;
}"""


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode=arena&theme={theme}#champ-select",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "document.querySelector('#view-champ-select .csv-duo-row')"
            " && document.querySelector("
            "'#view-champ-select .csv-augment-options .csv-augments-title')",
            timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        rows = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return rows


@pytest.fixture(scope="module")
def measured():
    return {}


def _rows(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


def _by(rows, state, cls, empty=False):
    return [r for r in rows
            if r[0] == state and cls in r[1].split() and r[6] == empty]


@pytest.mark.parametrize("theme", _THEMES)
def test_arena_pane_text_reaches_aa_on_its_surface(theme, measured,
                                                   mock_server, pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    # The fixture is me (hovering) + one locked ally + one empty slot.
    assert len(_by(rows, "duo", "csv-duo-cell-tag")) == 2, rows
    assert len(_by(rows, "duo", "csv-duo-cell-tag", empty=True)) == 1, rows
    for state, cls in [("duo", "csv-duo-cell-name"),
                       ("mine", "csv-augments-title"),
                       ("mine", "csv-augment-slot-grade"),
                       ("pick", "csv-augments-title"),
                       ("pick", "csv-empty")]:
        assert _by(rows, state, cls), f"{cls} ({state}) not rendered"
    low = []
    for state, cls, text, fg, bg, opacity, empty in rows:
        if empty:
            continue
        # The surface helper ignores opacity: a dimmed live element would
        # read AA here while rendering faint, so refuse one outright.
        assert opacity == 1, f"{cls!r} ({state}) rendered at {opacity}"
        assert fg and bg, f"no resolved surface under {cls!r}"
        r = _ratio(fg, bg)
        if r < 4.5:
            low.append(f"{cls} {text.strip()!r} ({state}) {r:.2f}:1")
    assert not low, f"{theme}: under 4.5:1 - " + "; ".join(low)


@pytest.mark.parametrize("theme", _THEMES)
def test_pick_one_title_keeps_its_accent_tint(theme, measured, mock_server,
                                              pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    title = _by(rows, "pick", "csv-augments-title")[0]
    fg = title[3]
    # The decision box is framed in the theme's secondary accent; lifting
    # the title for contrast must not wash it out to a neutral grey.
    assert max(fg[:3]) - min(fg[:3]) >= 60, (
        f"{theme}: pick-one title lost its accent tint {fg[:3]}")


@pytest.mark.parametrize("theme", ["hextech", "bloodmoon"])
def test_duo_tag_stays_dimmer_than_the_name_it_labels(
        theme, measured, mock_server, pw_browser):
    rows = _rows(measured, mock_server, pw_browser, theme)
    tags = _by(rows, "duo", "csv-duo-cell-tag")
    names = _by(rows, "duo", "csv-duo-cell-name")
    ally = [t for t in tags if t[2].strip() == "ALLY"]
    assert ally and names, rows
    assert _lum(ally[0][3]) < min(_lum(n[3]) for n in names), (
        f"{theme}: ALLY tag is as bright as the champion name")
