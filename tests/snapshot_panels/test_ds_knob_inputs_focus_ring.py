"""
tests/snapshot_panels/test_ds_knob_inputs_focus_ring.py
RM-1141 (s144 uiux): the Active Match Builds pane carries two DS knob
strips, the Fight model card (#csv-ds-knobs, web/js/panels/ds_knobs.js,
styled by web/css/panels/ds_knobs.css .dsk-knob > input) and the Stat
Sandbox card (#csv-ds-statcheck, web/js/panels/ds_statcheck.js, styled by
web/css/panels/ds_statcheck.css .dss-knob input): eight number inputs.

Both rules already take min-height var(--hit-min), but both set outline none
on :focus and draw only a 1px border-colour change, so a keyboard-focused
knob had no ring. The RM-1140 sibling (.dscombo-input / .dscombo-keystone
in the same pane) draws the one system ring (--focus-ring as the box-shadow,
outline none); these knobs now do too, and keep the hit floor. The Stat
Sandbox strip sits flush on the overflow: hidden .am-pane edge (measured:
input left 38px, pane left 37px plus its 1px border), which cut an outset
ring off, so its knobs take the inset ring (the RM-972 / RM-1137 rule);
the Fight model card pads its strip, so its knobs keep the outset ring.

Both renderers are driven directly against their live mounts with a
synthetic locked champion (the pattern test_ds_statcheck_view.py uses),
because the active-match cluster only unhides them for a live game.
Typing into a focused knob must keep focus and the caret: the Fight model
strip is built once per champion and its rows repaint under it, and the
Stat Sandbox strip is wired once and its readout repaints beside it.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_DSK = "#csv-ds-knobs .dsk-knob > input"
_DSS = "#csv-ds-statcheck .dss-knob input"

_FLOOR = """() => {
  const probe = document.createElement('div');
  probe.style.position = 'absolute';
  probe.style.height = 'var(--hit-min)';
  document.body.appendChild(probe);
  const floor = probe.getBoundingClientRect().height;
  probe.remove();
  return floor;
}"""

_RING = """(inset) => {
  const probe = document.createElement('div');
  probe.style.boxShadow = (inset ? 'inset ' : '') + 'var(--focus-ring)';
  document.body.appendChild(probe);
  const ring = getComputedStyle(probe).boxShadow;
  probe.remove();
  return ring;
}"""

# Mount both cards in the visible active-match Builds pane: the real mounts
# stay where index.html puts them, the cluster's own hide is bypassed by
# calling the renderers with a synthetic locked champion (222 = Jinx).
_MOUNT = """async () => {
  const k = await import('/js/panels/ds_knobs.js');
  const s = await import('/js/panels/ds_statcheck.js');
  if (k._resetDsKnobs) k._resetDsKnobs();
  if (s._resetDsStatcheck) s._resetDsStatcheck();
  const cs = { my_champion: 222, queue_id: 420 };
  k.renderDsKnobs(document.getElementById('csv-ds-knobs'), cs);
  s.renderDsStatcheck(document.getElementById('csv-ds-statcheck'), cs);
}"""


def _open(mock_server, pw_browser, theme="hextech"):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        """async () => {
          try {
            const m = await import('/js/panels/cc_conditional_pressure.js');
            const n = m.resolveChampNames ? m.resolveChampNames([222]) : [];
            return !!(n && n.length && n[0]);
          } catch (e) { return false; }
        }""",
        timeout=10_000,
    )
    page.evaluate(_MOUNT)
    page.wait_for_function(
        "(() => { const a = document.querySelectorAll("
        f"'{_DSK}'); const b = document.querySelectorAll('{_DSS}');"
        " return a.length === 4 && b.length === 4"
        " && [...a, ...b].every((e) => e.checkVisibility()); })()",
        timeout=10_000,
    )
    page.evaluate("document.fonts.ready")
    return ctx, page, errors


def test_knob_inputs_clear_the_hit_floor(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser)
    try:
        floor = page.evaluate(_FLOOR)
        heights = page.evaluate(
            "(sels) => sels.map((s) => [...document.querySelectorAll(s)]"
            ".map((e) => e.getBoundingClientRect().height))",
            [_DSK, _DSS],
        )
        overflow = page.evaluate(
            "document.documentElement.scrollWidth"
            " - document.documentElement.clientWidth"
        )
    finally:
        page.close()
        ctx.close()
    assert floor >= 40, f"--hit-min resolved {floor}"
    for sel, hs in zip((_DSK, _DSS), heights):
        assert len(hs) == 4, (sel, hs)
        assert all(h >= floor for h in hs), (
            f"{sel} heights {hs} under the {floor}px floor"
        )
    assert overflow <= 0, f"horizontal overflow {overflow}px"
    assert not errors, errors[:3]


@pytest.mark.parametrize("theme", _THEMES)
def test_knob_inputs_draw_the_system_focus_ring(mock_server, pw_browser, theme):
    ctx, page, errors = _open(mock_server, pw_browser, theme)
    try:
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        ring = page.evaluate(_RING, False)
        inset = page.evaluate(_RING, True)
        page.keyboard.press("Shift")
        got = page.evaluate(
            "(sels) => sels.flatMap((s) => [...document.querySelectorAll(s)]"
            ".map((el, i) => { el.focus(); const cs = getComputedStyle(el);"
            " const out = {sel: s, i, focused: document.activeElement === el,"
            " visible: el.matches(':focus-visible'),"
            " outline: cs.outlineStyle, shadow: cs.boxShadow};"
            # An outset ring paints 2px outside the box: record the first
            # clipping ancestor that would cut it off.
            " const r = el.getBoundingClientRect(); out.clip = null;"
            " for (let a = el.parentElement; a; a = a.parentElement) {"
            " const ac = getComputedStyle(a);"
            " if (ac.overflowX === 'visible' && ac.overflowY === 'visible')"
            " continue; const q = a.getBoundingClientRect();"
            " if (r.left - 2 < q.left || r.right + 2 > q.right"
            " || r.top - 2 < q.top || r.bottom + 2 > q.bottom) {"
            " out.clip = a.id || a.className; break; } }"
            " el.blur(); return out; }))",
            [_DSK, _DSS],
        )
    finally:
        page.close()
        ctx.close()
    assert ring not in ("", "none"), f"--focus-ring resolved {ring!r}"
    assert inset.endswith(" inset") and inset != ring, inset
    assert len(got) == 8, got
    for out in got:
        assert out["focused"] and out["visible"], out
        # The Fight model card pads its strip, so the outset ring clears
        # every clipping ancestor. The Stat Sandbox strip sits flush on the
        # overflow: hidden .am-pane edge, which cut the outset ring off, so
        # its knobs take the inset ring (the RM-972 / RM-1137 rule).
        want = ring if out["sel"] == _DSK else inset
        assert out["shadow"] == want, (
            f"{theme}: focused {out['sel']}[{out['i']}] box-shadow"
            f" {out['shadow']!r}, want {want!r}"
        )
        if out["sel"] == _DSK:
            assert out["clip"] is None, (
                f"{theme}: {out['sel']}[{out['i']}] ring clipped by"
                f" {out['clip']}"
            )
        assert out["outline"] == "none", (
            f"{theme}: focused {out['sel']}[{out['i']}] draws the UA outline"
        )
    # The geometry that makes inset the right choice: at least one Stat
    # Sandbox knob is flush with a clipping ancestor. If a layout change
    # ever pads it clear, the inset can be revisited.
    assert any(o["clip"] for o in got if o["sel"] == _DSS), got
    assert not errors, errors[:3]


@pytest.mark.parametrize("sel", ["#dsk-armor", "#csv-ds-statcheck "
                                 "input[data-knob='target_armor']"])
def test_typing_into_a_focused_knob_keeps_focus(mock_server, pw_browser, sel):
    # Each knob edit debounces a re-fetch and a repaint of the rows beside
    # the strip; the strip itself must never be rebuilt under the operator.
    ctx, page, errors = _open(mock_server, pw_browser)
    try:
        page.click(sel)
        page.keyboard.type("85")
        page.wait_for_timeout(900)
        got = page.evaluate(
            "(sel) => { const el = document.querySelector(sel);"
            " return {focused: document.activeElement === el,"
            " value: el.value}; }",
            sel,
        )
    finally:
        page.close()
        ctx.close()
    assert got["focused"], f"focus left {sel} while typing: {got}"
    assert got["value"] == "85", got
    assert not errors, errors[:3]
