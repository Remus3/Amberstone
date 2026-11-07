"""
tests/snapshot_panels/test_home_pick_name_contrast.py
S144-U-204 (s144 uiux): the Tonight's Pick champion name - the focal line
of Home's one focal card - reads at AA 4.5:1 or better on the card in every
theme, at rest and on hover, and its accent hue is kept.

THE DEFECT. MEASURED headless under /?ui_mock=1#home at 1920x1080 and
923x1280 (colour resolved by the browser and composited over the card's
own --surface-2, the PAIR, lane doc traps 3 and 4): .home-coach-pick-champ
(29 px / 800) painted bare --accent-2, which is the dark red pop in ember
and bloodmoon and a mid purple in arcane:
- bloodmoon 3.00:1, ember 3.05, arcane 3.28 (arcane is the boot theme);
- hextech 7.79, moonlit 9.27, terminal 9.95.
29 px is WCAG large text, so 3:1 is the bare floor and the three themes sat
ON it with no headroom. They also inverted the card's hierarchy: the quiet
reason line under the name (--text-dim, 18 px / 400, S144-U-200) measured
6.57 to 6.90 in those themes, more than twice the name it explains.
The hover colour (--good) measured 6.72 to 8.24 in all six themes.

THE FIX (web/css/panels/home.css): the name takes the RM-1550 lift,
color-mix(in oklab, var(--accent-2) 70%, var(--text)), the convention
already used for red text on these surfaces. After: ember 5.05, bloodmoon
5.07, arcane 5.23, hextech 9.50, moonlit 10.41, terminal 11.71. The mix is
in oklab toward the theme's own text colour, so the name keeps its theme
hue (checked below: within 15 degrees of each theme's --accent-2 hue, and
still saturated). Hover stays --good.

Alternatives rejected (measured): a 50 percent mix (6.89 to 6.95 in the red
and purple themes, over the reason line, but the red reads as pink and the
focal pop is gone); --accent (gold; 6.12 to 8.88, but the card's border,
portrait frame and top strip are --accent-2 tinted, so the name would leave
its card's colour); scoping the lift to three named themes (couples a panel
file to the theme list and outranks the :hover rule unless it is scoped
too).
"""
import colorsys

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 1080), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_NAME = ".home-coach-pick-champ"
_HUE_TOL = 15.0


def _hue(rgb):
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))[0] * 360

_MEASURE = """async (sel) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const e = document.querySelector(sel);
  if (!e || !e.checkVisibility()) return null;
  const s = surface(e);
  const cs = getComputedStyle(e);
  const probe = document.createElement('span');
  probe.style.color = 'var(--accent-2)';
  e.parentElement.appendChild(probe);
  const accent2 = rgba(getComputedStyle(probe).color);
  probe.style.color = 'var(--good)';
  const good = rgba(getComputedStyle(probe).color);
  probe.remove();
  return {
    text: e.textContent.trim(), fg: s ? over(rgba(cs.color), s) : null,
    bg: s, size: parseFloat(cs.fontSize),
    weight: parseInt(cs.fontWeight, 10), accent2, good,
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
        page.wait_for_selector(_NAME, state="visible", timeout=10_000)
        page.wait_for_function(
            "document.querySelector('.home-coach-pick-champ')"
            ".textContent.trim() !== '-'", timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        # The rule carries a 0.12 s colour transition: read settled values.
        page.wait_for_timeout(300)
        rest = page.evaluate(_MEASURE, _NAME)
        page.hover(_NAME)
        page.wait_for_timeout(300)
        hover = page.evaluate(_MEASURE, _NAME)
        reason = page.evaluate(_MEASURE, ".home-coach-pick-reason")
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return {"rest": rest, "hover": hover, "reason": reason}


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_pick_name_reads_at_aa_at_rest(theme, vp, measured,
                                           mock_server, pw_browser):
    row = _get(measured, mock_server, pw_browser, theme, vp)["rest"]
    assert row and row["bg"] is not None, (theme, vp, row)
    assert row["text"] not in ("", "-"), row
    # Anchor: still the 29 px / 800 focal line, not a shrunken one.
    assert row["size"] >= 24 and row["weight"] >= 700, row
    ratio = _ratio(row["fg"], row["bg"])
    assert ratio >= _AA, (
        f"Tonight's Pick name '{row['text']}' {ratio:.2f}:1 on {theme} at "
        f"{vp} (fg {row['fg']}, bg {row['bg']}), under AA {_AA}"
    )


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_the_pick_name_hover_is_good_and_reads_at_aa(theme, vp, measured,
                                                     mock_server, pw_browser):
    row = _get(measured, mock_server, pw_browser, theme, vp)["hover"]
    assert row and row["bg"] is not None, (theme, vp, row)
    assert row["fg"][:3] == row["good"][:3], (
        f"hover is not the theme's --good on {theme}: {row}")
    ratio = _ratio(row["fg"], row["bg"])
    assert ratio >= _AA, (theme, vp, round(ratio, 2), row)


@pytest.mark.parametrize("theme", _THEMES)
def test_the_pick_name_keeps_its_accent_hue(theme, measured,
                                            mock_server, pw_browser):
    """The lift moves the name toward --text only part way: its hue is
    within _HUE_TOL degrees of --accent-2's, it stays saturated, and it is
    not the reason line's colour."""
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    rest, reason = got["rest"], got["reason"]
    assert rest and reason, got
    accent2 = rest["accent2"][:3]
    fg = rest["fg"][:3]
    turn = abs(_hue(fg) - _hue(accent2)) % 360
    assert min(turn, 360 - turn) <= _HUE_TOL, (theme, fg, accent2, turn)
    # Not washed to grey: still clearly saturated.
    assert colorsys.rgb_to_hls(*(c / 255 for c in fg))[2] >= 0.4, (theme, fg)
    assert fg != reason["fg"][:3], (theme, fg, reason)
    assert reason["weight"] < rest["weight"], (theme, reason, rest)
