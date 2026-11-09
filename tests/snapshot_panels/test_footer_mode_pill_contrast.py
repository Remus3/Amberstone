"""
tests/snapshot_panels/test_footer_mode_pill_contrast.py
S144-U-199 (s144 uiux): the footer mode pill (#mode-pill, stamped by
web/js/main.js setMode as `mode-pill <tag>`, styled by the
`.mode-pill.<tag>` rules in web/css/panels/header.css and scaled down by
`footer .mode-pill` to --fs-xs 16 px weight 700) reaches WCAG AA 4.5:1 on
its resolved surface in every theme, for every mode tag it can carry.

16 px at weight 700 is not WCAG "large" text (that needs 18.66 px bold),
so the floor is 4.5:1, not 3:1.

MEASURED headless at 1920x1080 before the fix (colours resolved by the
browser and composited over the stacked backgrounds, lane doc traps 3 and
4): the TFT pill (solid --bad) and the ARENA pill (solid --advisory, which
only hextech and terminal define, so every other theme inherits hextech's
#E84057) measured 4.44:1 on arcane - the theme a fresh install boots on
(web/index.html theme bootstrap) - 4.48:1 on moonlit, and ARENA 4.49:1 on
ember. SR / ARAM / BRAWL / CLIENT were 6.98:1 or better everywhere.
After: both red pills take the RM-1550 lift every other red text label in
the dashboard already uses (--bad / --advisory mixed 70% toward --text in
oklab, e.g. .lv-mc-result-loss, .csv-enemy-wr-slot.is-bad), and a pin keeps
them red so the lift cannot drift into a neutral.

The TFT and ARENA cases are driven by the real state path (the snapshot
fixtures tft.json / arena.json, mode_key -> setMode -> className). The
other four tags re-stamp the class exactly as setMode does
(main.js setMode sets modePill.className to "mode-pill " + tag) on the
same pill,
so every tag is measured on the one real surface.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_TAGS = ["sr", "aram", "arena", "brawl", "tft", "client"]
_AA = 4.5

_MEASURE = """async (tags) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const pill = document.getElementById('mode-pill');
  const out = {
    real: pill.className,
    text: pill.textContent.trim(),
    in_footer: !!pill.closest('footer'),
    tags: {},
  };
  for (const tag of tags) {
    pill.className = `mode-pill ${tag}`;
    const cs = getComputedStyle(pill);
    const s = surface(pill);
    out.tags[tag] = {
      fg: s ? over(rgba(cs.color), s) : null,
      bg: s,
      size: parseFloat(cs.fontSize),
      weight: parseInt(cs.fontWeight, 10),
      visible: pill.checkVisibility(),
    };
  }
  return out;
}"""


def _measure(mock_server, pw_browser, theme, fixture):
    mock_server.set_fixture(fixture)
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "(t) => document.getElementById('mode-pill').classList"
            ".contains(t)",
            arg=fixture, timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        got = page.evaluate(_MEASURE, _TAGS)
    finally:
        page.close()
        ctx.close()
        mock_server._store["data"] = {}
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, fixture):
    key = (theme, fixture)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, fixture)
    return measured[key]


@pytest.mark.parametrize("fixture", ["tft", "arena"])
@pytest.mark.parametrize("theme", _THEMES)
def test_real_state_stamps_the_red_pill_at_aa(theme, fixture, measured,
                                              mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, fixture)
    assert got["real"] == f"mode-pill {fixture}", got["real"]
    assert got["text"] == fixture.upper(), got["text"]
    assert got["in_footer"], "the mode pill left the footer"
    row = got["tags"][fixture]
    assert row["visible"], f"{fixture} pill not visible on {theme}"
    assert row["bg"] is not None, f"no opaque surface under the pill on {theme}"
    # 16 px / 700: not WCAG large text, so the 4.5:1 floor applies.
    assert row["size"] < 18.66 or row["weight"] < 700, row
    ratio = _ratio(row["fg"], row["bg"])
    assert ratio >= _AA, (
        f"{fixture.upper()} pill {ratio:.2f}:1 on {theme} (fg {row['fg']}, "
        f"bg {row['bg']}), under AA {_AA}"
    )


@pytest.mark.parametrize("theme", _THEMES)
def test_every_mode_tag_reaches_aa(theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, "tft")
    assert got["in_footer"], "the mode pill left the footer"
    low = {}
    for tag, row in got["tags"].items():
        assert row["visible"], (tag, theme)
        assert row["bg"] is not None, (tag, theme)
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < _AA:
            low[tag] = round(ratio, 2)
    assert not low, f"under AA {_AA} on {theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_the_lifted_pills_stay_red(theme, measured, mock_server, pw_browser):
    """The lift mixes toward --text; a red pill must stay a red, not a
    pink-grey: red channel leads green and blue by a clear margin."""
    got = _get(measured, mock_server, pw_browser, theme, "tft")
    for tag in ("tft", "arena"):
        r, g, b = got["tags"][tag]["fg"][:3]
        assert r - max(g, b) >= 60, (tag, theme, (r, g, b))
