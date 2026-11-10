"""
tests/snapshot_panels/test_lobby_queue_fill_text_contrast.py
S144-U-250 (s144 uiux): the Lobby queue strip's two FILLED buttons - Find
Match (green) and Cancel Queue (red) - keep their two-line label at the
WCAG 1.4.3 AA text floor (4.5:1) on their own fill, at rest AND under a
real mouse hover, whenever the button is live, in all six themes.

THE DEFECT. MEASURED headless (polled LCU envelope, search_state
"Searching", a real page.hover on #lv-cancel-match) before the fix. The
label is --canvas (near-black) at --fs-xs 16 px, weight 800 / 700: not
large text, so the floor is 4.5:1. At rest it reads 4.88 (hextech) to
5.64 (terminal) on the --bad fill. The hover rule then mixed the fill
TOWARD --canvas - `color-mix(in srgb, var(--bad) 80%, var(--canvas))` -
darkening the red under dark text, so the label of the one control that
stops a search dropped to 3.43 (moonlit), 3.47 (hextech), 3.50 (arcane),
3.81 (bloodmoon), 3.89 (terminal), 3.90 (ember) the moment the pointer
reached it.

THE FIX (web/css/panels/header.css .lq-cancel:hover). The hover mixes the
fill toward --text instead, the Find Match hover precedent
(`color-mix(in srgb, var(--good) 85%, var(--text))`): the red lightens
under the dark label, so hover still reads as a change of fill and the
label gains contrast instead of losing it. After: hover 5.65 (moonlit),
5.68 (arcane), 5.71 (hextech), 6.36 (bloodmoon), 6.48 (ember), 6.74
(terminal); rest unchanged. Find Match was already AA at rest and hover.

Exempt and NOT measured here: a disabled or aria-disabled button (Cancel
Queue while idle and during a queue pop, Find Match while searching) -
WCAG 1.4.3 exempts inactive controls, and the opacity hold is how they
read as inactive (test_lobby_text_contrast states the same exemption).

Checked per theme and state, on its own page with the theme flipped
in-page behind a transitions-off sheet (the strip transitions background
and border, RM-1132) and reduced motion (the searching Find Match pulse): the live button's two label lines reach 4.5:1 over the
resolved fill, ancestor opacity folded in, at rest and under hover; the
hover really changes the fill (an inert hover would pass trivially); and
Cancel Queue keeps its --bad border under hover.

Harness: test_lobby_render_stability._open_lobby_stability with the
polled LCU envelope (ui_mock=False), as test_lobby_queue_buttons_focus_ring.
"""
import copy

import pytest

from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio
from tests.snapshot_panels.test_lobby_render_stability import (
    _POLL_LCU,
    _open_lobby_stability,
)

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_AA = 4.5
_SHEET = "*, *::before, *::after { transition: none !important; }"
# state -> (the button that is live in it, LCU phase that goes with it)
_STATES = {
    "Idle": ("lv-find-match", "Lobby"),
    "Searching": ("lv-cancel-match", "Matchmaking"),
}

_MEASURE = """(id) => {
""" + _HELPERS + """
  const alpha = (el) => {
    let a = 1;
    for (let n = el; n; n = n.parentElement) {
      a *= parseFloat(getComputedStyle(n).opacity);
    }
    return a;
  };
  const btn = document.getElementById(id);
  const bcs = getComputedStyle(btn);
  const root = getComputedStyle(document.documentElement);
  const lines = [];
  for (const sel of ['.lq-btn-line1', '.lq-btn-line2']) {
    const el = btn.querySelector(sel);
    if (!el || !el.checkVisibility()) continue;
    const fg = rgba(getComputedStyle(el).color);
    fg[3] *= alpha(el);
    const s = surface(el);
    lines.push({sel, text: el.textContent.trim(),
                fg: s ? over(fg, s) : null, bg: s,
                size: parseFloat(getComputedStyle(el).fontSize)});
  }
  return {
    theme: document.documentElement.dataset.theme,
    live: !btn.disabled && btn.getAttribute('aria-disabled') !== 'true',
    hovered: btn.matches(':hover'),
    fill: rgba(bcs.backgroundColor),
    border: rgba(bcs.borderTopColor),
    bad: rgba(root.getPropertyValue('--bad').trim()),
    lines,
  };
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, theme, state="Searching"):
    btn_id, phase = _STATES[state]
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, poll=True, ui_mock=False, lcu=lcu
    )
    try:
        # Reduced motion turns the searching Find Match pulse into a static
        # ring (header.css OQ4), so no animation runs at a colour read.
        page.emulate_media(reduced_motion="reduce")
        page.wait_for_function(
            "(() => { const b = document.getElementById('lv-find-match');"
            "  return b && !b.disabled; })()",
            timeout=15_000,
        )
        page.add_style_tag(content=_SHEET)
        if state == "Searching":
            lcu["phase"] = phase
            lcu["lobby"]["search_state"] = "Searching"
            page.wait_for_function(
                "(() => { const b = document.getElementById('lv-cancel-match');"
                "  return b && !b.disabled; })()",
                timeout=15_000,
            )
        page.evaluate(
            "(t) => document.documentElement.setAttribute('data-theme', t)",
            theme,
        )
        page.mouse.move(2, 2)
        rest = page.evaluate(_MEASURE, btn_id)
        page.hover("#" + btn_id)
        hover = page.evaluate(_MEASURE, btn_id)
    finally:
        page.close()
        ctx.close()
        mock_server._store["data"] = {}
    assert not errors, errors[:3]
    return {"rest": rest, "hover": hover}


def _get(measured, mock_server, pw_browser, state, theme):
    key = (state, theme)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, state)
    return measured[key]


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("state", sorted(_STATES))
def test_live_filled_button_label_reaches_aa_at_rest_and_hover(
        state, theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, state, theme)
    bad = []
    for phase in ("rest", "hover"):
        m = got[phase]
        assert m["theme"] == theme, (state, phase, m["theme"])
        # The measured button is the LIVE one, so the exemption cannot
        # hide a failure, and the hover read really is under the pointer.
        assert m["live"], (state, theme, phase)
        assert m["hovered"] is (phase == "hover"), (state, theme, phase)
        # Both label lines are on the page: an empty read cannot pass.
        assert [ln["sel"] for ln in m["lines"]] == [
            ".lq-btn-line1", ".lq-btn-line2"], (state, theme, phase, m)
        for ln in m["lines"]:
            assert ln["bg"] is not None, (state, theme, phase, ln)
            ratio = _ratio(ln["fg"], ln["bg"])
            if ratio < _AA:
                bad.append(f"{phase} {ln['text']!r} {ratio:.2f}:1")
    assert not bad, f"{state} {theme}: " + "; ".join(bad)


@pytest.mark.parametrize("theme", _THEMES)
@pytest.mark.parametrize("state", sorted(_STATES))
def test_hover_still_changes_the_fill(
        state, theme, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, state, theme)
    rest, hover = got["rest"]["fill"], got["hover"]["fill"]
    # An inert hover would pass the contrast check trivially; the fill
    # must visibly move (more than 8 levels on some channel).
    assert max(abs(a - b) for a, b in zip(rest[:3], hover[:3])) > 8, (
        state, theme, rest, hover)
    if state == "Searching":
        # Cancel Queue keeps its red border: the hover is a fill change.
        assert got["hover"]["border"] == got["hover"]["bad"], (
            theme, got["hover"]["border"], got["hover"]["bad"])
