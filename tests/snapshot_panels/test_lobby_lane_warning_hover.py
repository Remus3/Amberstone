"""
tests/snapshot_panels/test_lobby_lane_warning_hover.py
RM-1760 (s144 uiux) - hovering a Lobby lane trigger in a WARNING
state keeps its red --bad border.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#lobby at
1920x920 before the fix (the FUTURE row RM-1759 filed): the generic
hover rules `.lq-btn:hover:not(:disabled):not([aria-disabled="true"])`
and `.lq-lane-pref:hover:...` (specificity 0,4,0) out-rank the warning
rules `.lq-lane-pref.is-conflict` and `.lq-lane-pref.needs-pick`
(0,2,0), so the moment the pointer is on a warned trigger its red border
turns the --info "clickable" blue:
- a party lane CONFLICT on #lv-lane-primary: the red border went blue
  inside the red conflict outline (a mixed signal);
- the NEEDS-PICK secondary (primary moved off Fill): its dashed red
  border, the state's main visual cue beside the red cross glyph, went
  dashed blue.

THE FIX: header.css restates `border-color: var(--bad)` for the two
warning states on hover, at a higher specificity than the hover rules.
The Auto Accept and Party toggles keep the --info hover: their state is
also in their own text (On / Off, Open / Closed) and its colour, which
hover does not touch.

Border colours are read with the .lq-btn transition switched off, so a
read never lands mid-fade.
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS
from tests.snapshot_panels.test_lobby_lane_trigger_states import _doc, _open

_NO_FADE = ".lq-btn { transition: none !important; }"


def _token(page, name):
    """A colour token resolved to its computed rgb() string."""
    return page.evaluate("""(n) => {
      const d = document.createElement('div');
      d.style.color = 'var(' + n + ')';
      document.body.appendChild(d);
      const c = getComputedStyle(d).color;
      d.remove();
      return c;
    }""", name)


def _border(page, tid):
    return page.evaluate("""(t) => {
      const cs = getComputedStyle(document.getElementById(t));
      return {color: cs.borderTopColor, style: cs.borderTopStyle,
              outline: cs.outlineColor};
    }""", tid)


@pytest.mark.parametrize("vp", VIEWPORTS, ids=[f"{w}x{h}" for w, h in VIEWPORTS])
def test_conflicted_primary_keeps_red_border_on_hover(mock_server, pw_browser, vp):
    ctx, page, errors = _open(pw_browser, mock_server, vp,
                              _doc("MIDDLE", "BOTTOM", mate_first="MIDDLE"))
    try:
        page.wait_for_function(
            "() => document.getElementById('lv-lane-primary')"
            ".classList.contains('is-conflict')", timeout=10_000)
        page.add_style_tag(content=_NO_FADE)
        bad = _token(page, "--bad")
        page.mouse.move(0, 0)
        rest = _border(page, "lv-lane-primary")
        assert rest["color"] == bad, (rest, bad)
        page.hover("#lv-lane-primary")
        hov = _border(page, "lv-lane-primary")
        assert hov["color"] == bad, (hov, bad)
        # The conflict outline stays red too.
        assert hov["outline"] == bad, (hov, bad)
        # Hovered AND keyboard-focused: the border stays red and the
        # RM-1209 2px --accent focus ring still replaces the outline.
        page.locator("#lv-lane-primary").focus()
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        assert page.evaluate(
            "() => document.getElementById('lv-lane-primary')"
            ".matches(':focus-visible:hover')")
        foc = _border(page, "lv-lane-primary")
        assert foc["color"] == bad, (foc, bad)
        assert foc["outline"] == _token(page, "--accent"), foc
        assert page.evaluate(
            "() => getComputedStyle(document.getElementById("
            "'lv-lane-primary')).outlineWidth") == "2px"
        assert not errors, errors
    finally:
        ctx.close()


def test_needs_pick_secondary_keeps_red_dashed_border_on_hover(
        mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("FILL", "FILL"))
    try:
        page.add_style_tag(content=_NO_FADE)
        # Primary FILL -> MIDDLE leaves the secondary needing a pick
        # (under ui_mock no lobby tick runs, so the state holds).
        page.evaluate("""() => {
          document.getElementById('lv-lane-primary').click();
          document.querySelector('#lv-lane-popup '
            + '.lobby-lane-popup-cell[data-pref="MIDDLE"]').click();
        }""")
        page.wait_for_function(
            "() => document.getElementById('lv-lane-secondary')"
            ".classList.contains('needs-pick')", timeout=10_000)
        bad = _token(page, "--bad")
        page.mouse.move(0, 0)
        rest = _border(page, "lv-lane-secondary")
        assert rest == {**rest, "color": bad, "style": "dashed"}, (rest, bad)
        page.hover("#lv-lane-secondary")
        hov = _border(page, "lv-lane-secondary")
        assert hov["color"] == bad, (hov, bad)
        assert hov["style"] == "dashed", hov
        assert page.evaluate(
            "() => document.getElementById('lv-lane-secondary')"
            ".classList.contains('needs-pick')"), "state left during hover"
        assert not errors, errors
    finally:
        ctx.close()


def test_plain_lane_trigger_still_lights_info_on_hover(mock_server, pw_browser):
    """Positive control: with no warning state the trigger's hover is the
    --info "clickable" border, so the warning tests above are not passing
    because hover does nothing."""
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("MIDDLE", "BOTTOM", mate_first="TOP"))
    try:
        page.add_style_tag(content=_NO_FADE)
        info = _token(page, "--info")
        page.mouse.move(0, 0)
        assert not page.evaluate(
            "() => document.getElementById('lv-lane-primary')"
            ".classList.contains('is-conflict')")
        rest = _border(page, "lv-lane-primary")
        assert rest["color"] != info, rest
        page.hover("#lv-lane-primary")
        assert _border(page, "lv-lane-primary")["color"] == info
        page.hover("#lv-lane-secondary")
        assert _border(page, "lv-lane-secondary")["color"] == info
        assert not errors, errors
    finally:
        ctx.close()


def test_state_toggles_keep_info_hover_and_their_state_text(
        mock_server, pw_browser):
    """The ruling's other half: Auto Accept and Party keep the --info
    hover border, because their state is also in their own coloured
    text, which hover leaves alone."""
    ctx, page, errors = _open(pw_browser, mock_server, VIEWPORTS[0],
                              _doc("MIDDLE", "BOTTOM"))
    try:
        page.add_style_tag(content=_NO_FADE)
        info = _token(page, "--info")
        page.mouse.move(0, 0)

        def line2(tid):
            return page.evaluate("""(t) => {
              const el = document.querySelector('#' + t + ' .lq-btn-line2');
              return {text: el.textContent.trim(),
                      color: getComputedStyle(el).color};
            }""", tid)

        for tid in ("lv-auto-accept", "lv-party-toggle"):
            rest = line2(tid)
            assert rest["text"], (tid, rest)
            page.hover("#" + tid)
            assert _border(page, tid)["color"] == info, tid
            assert line2(tid) == rest, (tid, rest)
            page.mouse.move(0, 0)
        assert not errors, errors
    finally:
        ctx.close()
