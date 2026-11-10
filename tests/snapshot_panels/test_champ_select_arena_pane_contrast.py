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

S144-U-271 (s144 uiux cycle 265) reverses RM-1197's exclusion of the
empty slots. The empty partner slot (.csv-duo-cell.is-empty: "?" /
"ALLY" / "waiting...") and the empty enemy slot (.csv-arena-cell.is-empty
in #csv-enemies-list: "?" / "-") were faded with opacity 0.55 on the whole
cell. MEASURED the same way: the empty "ALLY" tag read 2.89 (hextech) to
3.33 (terminal):1, and the empty enemy "-" 4.42:1 on arcane. The S144-U-243
ruling governs an empty state: its text drops the opacity and takes
--text-dim. Both cells now keep only their dashed border as the empty cue,
every text in them sits at opacity 1 and reaches AA, and it stays dimmer
than the filled cell beside it (the hierarchy test below). The shared
surface helper ignores opacity, so every measured element must render at
opacity 1.
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
                 ['pick', '.csv-augment-options'],
                 ['enemy', '#csv-enemies-list']];
  for (const [state, sel] of hosts) {
    const host = document.querySelector('#view-champ-select ' + sel);
    if (!host) continue;
    for (const e of host.querySelectorAll('*')) {
      if (![...e.childNodes].some(
          (n) => n.nodeType === 3 && n.textContent.trim())) continue;
      if (!e.checkVisibility()) continue;
      const s = surface(e);
      const cell = e.closest('.csv-duo-cell, .csv-arena-cell');
      out.push([state, e.className, e.textContent,
                s ? over(rgba(getComputedStyle(e).color), s) : null, s,
                op(e),
                !!e.closest('.csv-duo-cell.is-empty, .csv-arena-cell.is-empty'),
                parseFloat(getComputedStyle(e).fontSize),
                cell ? getComputedStyle(cell).borderTopStyle : '']);
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
    # S144-U-271: the empty enemy slots are measured too (the fixture leaves
    # some sub-team cells unpicked), beside the filled ones.
    assert _by(rows, "enemy", "csv-arena-cell-name", empty=True), rows
    assert _by(rows, "enemy", "csv-arena-cell-name"), rows
    low = []
    for state, cls, text, fg, bg, opacity, _empty, size, _border in rows:
        # The surface helper ignores opacity: a dimmed element would read AA
        # here while rendering faint, so refuse one outright - empty slots
        # included (S144-U-271).
        assert opacity == 1, f"{cls!r} {text.strip()!r} ({state}) rendered at {opacity}"
        assert fg and bg, f"no resolved surface under {cls!r}"
        r = _ratio(fg, bg)
        # WCAG 1.4.3: 3:1 for large text (24px and up), 4.5:1 otherwise.
        if r < (3.0 if size >= 24 else 4.5):
            low.append(f"{cls} {text.strip()!r} ({state}) {r:.2f}:1")
    assert not low, f"{theme}: under AA - " + "; ".join(low)


@pytest.mark.parametrize("theme", _THEMES)
def test_empty_slots_read_as_empty_below_the_filled_cells(
        theme, measured, mock_server, pw_browser):
    # S144-U-271: with the cell-wide fade gone, the empty cue is the dashed
    # border plus --text-dim text, and an empty slot's text never outshines
    # the filled cell next to it.
    rows = _rows(measured, mock_server, pw_browser, theme)
    e_duo = [r for r in rows if r[0] == "duo" and r[6]]
    e_enemy = [r for r in rows if r[0] == "enemy" and r[6]]
    assert e_duo and e_enemy, rows
    for r in e_duo + e_enemy:
        assert r[8] == "dashed", f"{theme}: empty {r[1]!r} cell lost its dashed border"
    for r in _by(rows, "duo", "csv-duo-cell-name") + _by(
            rows, "enemy", "csv-arena-cell-name"):
        assert r[8] == "solid", f"{theme}: filled {r[1]!r} cell is not solid"
    # The empty partner slot's words ("ALLY" / "waiting...") are --text-dim,
    # the tone of the filled ALLY tag on the same --surface-2 cell.
    ally = [t for t in _by(rows, "duo", "csv-duo-cell-tag")
            if t[2].strip() == "ALLY"]
    assert ally, rows
    words = [r for r in e_duo if "csv-duo-cell-icon" not in r[1].split()]
    assert {r[2].strip() for r in words} == {"ALLY", "waiting..."}, words
    for r in words:
        assert r[3][:3] == ally[0][3][:3], (
            f"{theme}: empty {r[2].strip()!r} is {r[3][:3]}, not --text-dim"
            f" {ally[0][3][:3]}")
    filled_duo = min(_lum(n[3]) for n in _by(rows, "duo", "csv-duo-cell-name"))
    for r in words:
        assert _lum(r[3]) < filled_duo, (
            f"{theme}: empty {r[2].strip()!r} as bright as a picked name")
    filled_enemy = min(_lum(n[3]) for n in _by(rows, "enemy", "csv-arena-cell-name"))
    for r in _by(rows, "enemy", "csv-arena-cell-name", empty=True):
        assert _lum(r[3]) < filled_enemy, (
            f"{theme}: empty enemy {r[2].strip()!r} as bright as a picked name")


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
