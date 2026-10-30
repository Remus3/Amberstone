"""
tests/snapshot_panels/test_ds_combo_controls_hit_floor.py
RM-1140 (s144 uiux): the Active Match combo timeline card
(#csv-sugg-ds-combo, built by web/js/panels/ds_combo.js renderDsCombo and
styled in web/css/panels/ds_combo.css) carries the only two form controls in
the Builds pane: the action-queue text input (#csv-sugg-ds-combo-input) and
the keystone rune select (#csv-sugg-ds-combo-keystone). Nothing pinned them.

MEASURED under /?ui_mock=1&mode=<sr|aram|arena|brawl>#active-match at
1920x1080 before the fix: both controls were 34px tall on all four modes and
all six themes, under the resolved --hit-min (42px), and a keyboard-focused
control drew only a 1px border-colour change (outline none, no ring). No
documented exception covers them: docs/UI_SCALE_SPEC_V2.md gives the peer
controls (.ub-toolbar input, .ub-field input / select) an h-min of
var(--hit-min). So both now take the floor and draw the one system ring
(--focus-ring as the box-shadow, outline none), the pattern
#bi-duration-mount .dw-champ-input already uses.

The row stays one line (the select sits beside the input at the same top and
height), and typing into the focused input keeps focus and the caret, the
contract the panel was built around (the input is never repainted).
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MODES = ["sr", "aram", "arena", "brawl"]
_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_INPUT = "#csv-sugg-ds-combo-input"
_SELECT = "#csv-sugg-ds-combo-keystone"

_FLOOR = """() => {
  // Absolute, so a flex-column body cannot shrink the probe below the token.
  const probe = document.createElement('div');
  probe.style.position = 'absolute';
  probe.style.height = 'var(--hit-min)';
  document.body.appendChild(probe);
  const floor = probe.getBoundingClientRect().height;
  probe.remove();
  return floor;
}"""

_RING = """() => {
  const probe = document.createElement('div');
  probe.style.boxShadow = 'var(--focus-ring)';
  document.body.appendChild(probe);
  const ring = getComputedStyle(probe).boxShadow;
  probe.remove();
  return ring;
}"""

_BOX = """(sel) => {
  const el = document.querySelector(sel);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return {top: r.top, w: r.width, h: r.height, shown: el.checkVisibility()};
}"""


def _open(mock_server, pw_browser, mode, theme="hextech"):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url
        + f"/?ui_mock=1&mode={mode}&theme={theme}#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        "(() => { const i = document.getElementById("
        "'csv-sugg-ds-combo-input');"
        " return !!i && i.checkVisibility(); })()",
        timeout=10_000,
    )
    page.evaluate("document.fonts.ready")
    return ctx, page, errors


@pytest.mark.parametrize("mode", _MODES)
def test_combo_controls_clear_the_hit_floor(mock_server, pw_browser, mode):
    ctx, page, errors = _open(mock_server, pw_browser, mode)
    try:
        floor = page.evaluate(_FLOOR)
        inp = page.evaluate(_BOX, _INPUT)
        sel = page.evaluate(_BOX, _SELECT)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
    finally:
        page.close()
        ctx.close()
    assert floor >= 40, f"--hit-min resolved {floor}"
    assert inp and inp["shown"], f"{mode}: combo input not shown: {inp}"
    assert sel and sel["shown"], f"{mode}: keystone select not shown: {sel}"
    assert inp["h"] >= floor, (
        f"{mode}: combo input is {inp['h']}px tall, floor {floor}px"
    )
    assert sel["h"] >= floor, (
        f"{mode}: keystone select is {sel['h']}px tall, floor {floor}px"
    )
    assert sel["w"] >= floor, f"{mode}: keystone select is {sel['w']}px wide"
    # One row: the peer select sits beside the input, same top, same height.
    assert abs(inp["top"] - sel["top"]) < 1, (inp, sel)
    assert abs(inp["h"] - sel["h"]) < 1, (inp, sel)
    assert overflow <= 0, f"{mode}: horizontal overflow {overflow}px"
    assert not errors, errors[:3]


@pytest.mark.parametrize("theme", _THEMES)
def test_combo_controls_draw_the_system_focus_ring(
    mock_server, pw_browser, theme
):
    ctx, page, errors = _open(mock_server, pw_browser, "sr", theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        ring = page.evaluate(_RING)
        page.keyboard.press("Shift")
        got = {}
        for sel in (_INPUT, _SELECT):
            got[sel] = page.evaluate(
                "(sel) => { const el = document.querySelector(sel);"
                " el.focus(); const cs = getComputedStyle(el);"
                " const out = {focused: document.activeElement === el,"
                " visible: el.matches(':focus-visible'),"
                " outline: cs.outlineStyle, shadow: cs.boxShadow};"
                " el.blur(); return out; }",
                sel,
            )
    finally:
        page.close()
        ctx.close()
    assert ring not in ("", "none"), f"--focus-ring resolved {ring!r}"
    for sel, out in got.items():
        assert out["focused"] and out["visible"], (sel, out)
        assert out["shadow"] == ring, (
            f"{theme}: focused {sel} box-shadow {out['shadow']!r},"
            f" ring {ring!r}"
        )
        assert out["outline"] == "none", (
            f"{theme}: focused {sel} draws the UA outline ({out['outline']})"
        )
    assert not errors, errors[:3]


def test_typing_into_the_focused_input_keeps_focus(mock_server, pw_browser):
    # The input fires input/change into the host replay; the panel must never
    # repaint the input, so focus and the caret survive the keystrokes.
    ctx, page, errors = _open(mock_server, pw_browser, "sr")
    try:
        page.click(_INPUT)
        page.keyboard.press("End")
        page.keyboard.type(", Q")
        page.wait_for_timeout(600)
        got = page.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " return {focused: document.activeElement === el,"
            " value: el.value, caret: el.selectionStart,"
            " len: el.value.length}; }",
            _INPUT,
        )
    finally:
        page.close()
        ctx.close()
    assert got["focused"], f"focus left the combo input while typing: {got}"
    assert got["value"].endswith(", Q"), got
    assert got["caret"] == got["len"], f"caret moved: {got}"
    assert not errors, errors[:3]
