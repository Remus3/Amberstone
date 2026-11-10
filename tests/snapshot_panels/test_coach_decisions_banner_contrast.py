"""
tests/snapshot_panels/test_coach_decisions_banner_contrast.py
S144-U-269 (s144 uiux): the coach decisions banner (#coach-decisions, the
live "Dragon in 45s - 3 enemies missing" call with its CONTEST / GIVE /
SKIP buttons) keeps every line at the WCAG 1.4.3 AA text floor (4.5:1) at
rest AND under a real mouse hover, and shows a visible keyboard focus ring
(WCAG 2.4.7, ring at the 1.4.11 3:1 non-text floor), in all six themes.

WHERE IT RENDERS. MEASURED headless (a routed /api/decisions answering one
pending objective_contest decision, the core/decision_detector shape) in
every view: the banner sits between the header and the view sections, so
it is LIVE in home, lobby, champ-select, active-match, last-match,
session, history, settings, replay, user-builds and build-insights (a
73 px box at 1920x920). Only the overlay shell hides it (overlay.css).

THE DEFECTS, measured before the fix over the banner's own amber
gradient (its 0.08 stop, the lighter one, is the worst case for light
text):
- SKIP (the dismiss button) paints --text-faint, 4.67 (hextech) to 5.13
  (terminal) at rest. Its hover lays rgba(255,255,255,0.08) under the
  label, and the label of the only way to dismiss a call dropped to 3.73
  (hextech), 3.88 (ember), 3.91 (arcane), 3.97 (bloodmoon), 4.00
  (moonlit) and 4.20 (terminal) the moment the pointer reached it.
  CONTEST and GIVE stay at 5.27 or above under the same hover.
- No .coach-decision-btn:focus-visible rule existed: a keyboard user got
  only the UA default ring, where every other dashboard button carries
  the 2 px --accent ring (header.css .lq-mode-trigger, .lobby-lane-popup-
  cell, champ_select_view.css .csv-rune-save-default).

THE FIX (web/css/panels/coach_decisions.css). SKIP lifts to --text-dim
under the pointer (5.34 hextech to 6.83 terminal): the hover now reads as
a brighter label on the lighter fill, and its rest colour is unchanged,
so SKIP stays the quietest button at rest (a rest-colour lift to
--text-dim would have out-shone CONTEST in hextech). Every button takes
`outline: 2px solid var(--accent); outline-offset: 2px` on
:focus-visible, 6.90 (arcane) to 9.87 (moonlit) on the banner.

Checked per theme on /?ui_mock=1&mode=sr&theme=<t>#active-match at
1920x920, behind a transitions-off sheet and reduced motion, after the
row's slide-in animation has finished: the five banner lines (title,
subtitle, three buttons) are on the page with their texts (an empty read
cannot pass) and reach 4.5:1 at rest; each button, really hovered,
reaches 4.5:1 over its own hover fill and the hover still lays a fill (an
inert hover would pass trivially); SKIP at rest is dimmer than CONTEST
and GIVE; each button, keyboard focused, matches :focus-visible and draws
a solid ring at least 2 px wide at 3:1 or better on the banner.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio
from itertools import starmap

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_AA = 4.5
_RING = 3.0
_SHEET = "*, *::before, *::after { transition: none !important; }"
# One pending decision in the core/decision_detector.Decision.to_dict()
# shape (objective_contest detector; synthetic champion names).
_PENDING = {"pending": [{
    "id": "objective_contest:Dragon:300",
    "type": "objective_contest",
    "title": "Dragon in 45s - 3 enemies missing",
    "subtitle": "Missing: Vi (river), Ahri (mid), Jinx (bot)",
    "options": ["contest", "give"],
    "created_at_unix": 1.0,
    "created_at_game_time": 255.0,
    "expires_at_game_time": 390.0,
    "context": {},
}]}
_LINES = {
    "coach-decision-title": "Dragon in 45s - 3 enemies missing",
    "coach-decision-sub": "Missing: Vi (river), Ahri (mid), Jinx (bot)",
    "contest": "CONTEST",
    "give": "GIVE",
    "skip": "SKIP",
}
_CHOICES = ("contest", "give", "skip")

# The banner's background stops (its own gradient over the page surface)
# and the colour of one element, read in one evaluate.
_MEASURE = """async (what) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const sec = document.getElementById('coach-decisions');
  const base = surface(sec);
  const stops = (getComputedStyle(sec).backgroundImage
    .match(/rgba?\\([^)]*\\)/g) || []).map(rgba);
  const bgs = stops.map((s) => over(s, base));
  const pick = (key) => key.startsWith('coach-decision-')
    ? sec.querySelector('.' + key)
    : sec.querySelector('.coach-decision-btn[data-choice="' + key + '"]');
  const out = {};
  for (const key of what) {
    const el = pick(key);
    if (!el || !el.checkVisibility()) continue;
    const cs = getComputedStyle(el);
    const fill = rgba(cs.backgroundColor);
    out[key] = {
      text: el.textContent.trim(), color: rgba(cs.color), fill,
      hover: el.matches(':hover'), focus: el.matches(':focus-visible'),
      active: document.activeElement === el,
      outline: [cs.outlineStyle, parseFloat(cs.outlineWidth),
                rgba(cs.outlineColor)],
      fg: bgs.map((b) => over(rgba(cs.color), over(fill, b))),
      bg: bgs.map((b) => over(fill, b)),
      ring: bgs.map((b) => over(rgba(cs.outlineColor), b)),
      rings: bgs,
    };
  }
  return {theme: document.documentElement.dataset.theme || 'hextech',
          hidden: sec.hidden, stops: stops.length, lines: out};
}"""


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.emulate_media(reduced_motion="reduce")
    page.route("**/api/decisions", lambda r: r.fulfill(
        status=200, content_type="application/json",
        body=json.dumps(_PENDING)))
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    got = {}
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'"
            " && !!document.querySelector('#coach-decisions li .coach-decision-btn')",
            timeout=10_000)
        page.add_style_tag(content=_SHEET)
        # The row's coachDecisionIn slide-in has finished before any read.
        page.wait_for_function(
            "() => document.getAnimations().length === 0", timeout=10_000)
        got["rest"] = page.evaluate(_MEASURE, list(_LINES))
        got["hover"] = {}
        for choice in _CHOICES:
            sel = f'#coach-decisions .coach-decision-btn[data-choice="{choice}"]'
            page.hover(sel)
            got["hover"][choice] = page.evaluate(_MEASURE, [choice])
        page.mouse.move(5, 905)
        got["focus"] = {}
        for choice in _CHOICES:
            sel = f'#coach-decisions .coach-decision-btn[data-choice="{choice}"]'
            # Keyboard focus: land next to the button, then Tab onto it.
            page.focus(sel)
            page.keyboard.press("Shift+Tab")
            page.keyboard.press("Tab")
            got["focus"][choice] = page.evaluate(_MEASURE, [choice])
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got["rest"]["theme"] == theme, (
        f"booted on {got['rest']['theme']}, not {theme}")
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme):
    if theme not in measured:
        measured[theme] = _measure(mock_server, pw_browser, theme)
    return measured[theme]


def _lum(c) -> float:
    def ch(v):
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _worst(ln, fg_key="fg", bg_key="bg") -> float:
    pairs = list(zip(ln[fg_key], ln[bg_key]))
    assert pairs, ln
    return min(starmap(_ratio, pairs))


@pytest.mark.parametrize("theme", _THEMES)
def test_banner_lines_reach_aa_at_rest(theme, measured, mock_server,
                                       pw_browser):
    rest = _get(measured, mock_server, pw_browser, theme)["rest"]
    assert rest["hidden"] is False, rest
    # The gradient's stops were read, so the surface is the banner's own.
    assert rest["stops"] >= 2, rest["stops"]
    lines = rest["lines"]
    assert {k: v["text"] for k, v in lines.items()} == _LINES, sorted(lines)
    bad = [f"{k} {ln['text']!r} {_worst(ln):.2f}:1"
           for k, ln in sorted(lines.items()) if _worst(ln) < _AA]
    assert not bad, f"{theme} rest under {_AA}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_banner_buttons_reach_aa_under_hover(theme, measured, mock_server,
                                             pw_browser):
    hover = _get(measured, mock_server, pw_browser, theme)["hover"]
    bad = []
    for choice in _CHOICES:
        ln = hover[choice]["lines"].get(choice)
        assert ln is not None, (theme, choice, hover[choice])
        assert ln["hover"] is True, (theme, choice, "not hovered")
        # The hover still lays a fill: an inert hover would pass trivially.
        assert ln["fill"][3] > 0, (theme, choice, ln["fill"])
        if _worst(ln) < _AA:
            bad.append(f"{choice} {_worst(ln):.2f}:1")
    assert not bad, f"{theme} hover under {_AA}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
def test_skip_is_the_quietest_button_at_rest(theme, measured, mock_server,
                                             pw_browser):
    lines = _get(measured, mock_server, pw_browser, theme)["rest"]["lines"]
    skip = _lum(lines["skip"]["fg"][0])
    for choice in ("contest", "give"):
        assert skip < _lum(lines[choice]["fg"][0]), (theme, choice)


@pytest.mark.parametrize("theme", _THEMES)
def test_banner_buttons_show_a_focus_ring(theme, measured, mock_server,
                                          pw_browser):
    focus = _get(measured, mock_server, pw_browser, theme)["focus"]
    bad = []
    for choice in _CHOICES:
        ln = focus[choice]["lines"].get(choice)
        assert ln is not None, (theme, choice, focus[choice])
        assert ln["active"] is True, (theme, choice, "not focused")
        assert ln["focus"] is True, (theme, choice, "not :focus-visible")
        style, width, _color = ln["outline"]
        if style != "solid" or width < 2:
            bad.append(f"{choice} outline {style} {width}px")
            continue
        ratio = _worst(ln, "ring", "rings")
        if ratio < _RING:
            bad.append(f"{choice} ring {ratio:.2f}:1")
    assert not bad, f"{theme} focus: " + "; ".join(bad)
