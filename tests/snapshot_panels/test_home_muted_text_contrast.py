"""
tests/snapshot_panels/test_home_muted_text_contrast.py
S144-U-200 (s144 uiux): every text line on the Home view reaches its WCAG
contrast floor on its resolved surface, in every theme, at the 1920x1080
baseline and the 923x1280 companion window.

THE DEFECT. MEASURED headless under /?ui_mock=1#home before the fix
(colours resolved by the browser and composited over the stacked
backgrounds, lane doc traps 3 and 4 - the PAIR is fg on its own surface):
three secondary lines painted --text-faint and sat under AA 4.5:1:
- .home-recent-meta (the RECENT row's mode / duration / CS line, 18 px /
  400 on the card's --surface-3): 3.64:1 arcane - the theme a fresh install
  boots on - 3.74 ember, 3.78 moonlit, 3.85 bloodmoon, 3.94 hextech; only
  terminal passed (4.59);
- .home-wl-form (the hero's "13-7 (65%)", 16 px / 600): 4.31 arcane, 4.39
  ember, 4.46 hextech, 4.48 moonlit;
- .home-coach-pick-reason (Tonight's Pick reason line, 18 px / 400): the
  same 4.31 / 4.39 / 4.46 / 4.48.
None is WCAG large text (24 px, or 18.66 px at 700), so the floor is 4.5.

THE FIX (web/css/panels/home.css): the three lines take --text-dim, the
dashboard's secondary-text token, instead of --text-faint. The hierarchy
check below keeps them dimmer than the line they annotate.

Large text (the 29 px / 800 Tonight's Pick champion name) is held to 3:1;
it measured 3.00:1 on bloodmoon, 3.06 ember, 3.28 arcane - at the floor,
not under it, and filed as a FUTURE row in the QA ledger.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 1080), (923, 1280)]
_AA = 4.5
_AA_LARGE = 3.0
_FIXED = (".home-recent-meta", ".home-wl-form", ".home-coach-pick-reason")

_MEASURE = """async (fixed) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const host = document.getElementById('home-overlay');
  const row = (e) => {
    const s = surface(e);
    const cs = getComputedStyle(e);
    return {
      cls: String(e.className), text: e.textContent.trim().slice(0, 40),
      fg: s ? over(rgba(cs.color), s) : null, bg: s,
      size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
    };
  };
  const all = [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(row);
  const named = {};
  for (const sel of fixed) {
    named[sel] = [...host.querySelectorAll(sel)]
      .filter((e) => e.checkVisibility()).map(row);
  }
  const pair = (sel) => {
    const e = host.querySelector(sel);
    return e && e.checkVisibility() ? row(e) : null;
  };
  return {
    all, named,
    champ: pair('.home-recent-card .home-recent-champ'),
    meta: pair('.home-recent-card .home-recent-meta'),
    pick: pair('.home-coach-pick-champ'),
    reason: pair('.home-coach-pick-reason'),
  };
}"""


def _measure(mock_server, pw_browser, theme, vp):
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#home",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_selector(".home-recent-card", state="visible",
                               timeout=10_000)
        page.wait_for_selector(".home-coach-pick-reason", state="visible",
                               timeout=10_000)
        page.wait_for_selector(".home-wl-form", state="visible",
                               timeout=10_000)
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        got = page.evaluate(_MEASURE, list(_FIXED))
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


def _large(row):
    return row["size"] >= 24 or (row["size"] >= 18.66 and row["weight"] >= 700)


_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_three_secondary_lines_reach_aa(theme, vp, measured,
                                            mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    for sel in _FIXED:
        rows = got["named"][sel]
        assert rows, f"no visible {sel} on {theme} at {vp}"
        for row in rows:
            assert row["bg"] is not None, (sel, theme, row)
            # None of the three is WCAG large text: the 4.5 floor applies.
            assert not _large(row), (sel, row)
            ratio = _ratio(row["fg"], row["bg"])
            assert ratio >= _AA, (
                f"{sel} '{row['text']}' {ratio:.2f}:1 on {theme} at {vp} "
                f"(fg {row['fg']}, bg {row['bg']}), under AA {_AA}"
            )


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_home_text_line_reaches_its_floor(theme, vp, measured,
                                                mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    assert len(got["all"]) >= 20, f"Home rendered too little text: {got['all']}"
    low = []
    for row in got["all"]:
        assert row["bg"] is not None, (theme, vp, row)
        floor = _AA_LARGE if _large(row) else _AA
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < floor:
            low.append((row["cls"], row["text"], round(ratio, 2), floor))
    assert not low, f"under the WCAG floor on {theme} at {vp}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_the_secondary_lines_stay_under_the_line_they_annotate(
        theme, measured, mock_server, pw_browser):
    """The lift must not invert the hierarchy: a RECENT card's meta line
    stays dimmer than its champion name, and the Tonight's Pick reason
    stays a different, quieter colour than the accent champion name."""
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    champ, meta = got["champ"], got["meta"]
    assert champ and meta, got
    assert _ratio(meta["fg"], meta["bg"]) < _ratio(champ["fg"], champ["bg"]), (
        theme, meta, champ)
    pick, reason = got["pick"], got["reason"]
    assert pick and reason, got
    assert reason["fg"][:3] != pick["fg"][:3], (theme, reason, pick)
    assert reason["weight"] < pick["weight"], (theme, reason, pick)
