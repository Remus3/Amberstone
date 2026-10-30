"""
tests/snapshot_panels/test_user_builds_spell_chooser_keyboard.py
RM-1133 (s144 uiux): the User Builds summoner spell chooser - the D / F
slot buttons (web/index.html #ub-sp-slot-d / #ub-sp-slot-f) and the icon
grid cells (.ub-sp-cell, main.js _ubSpellRenderGrid) - measured from the
keyboard in headless Chromium under /?ui_mock=1#user-builds.

Filed as "may throw focus to <body> on a keyboard pick, as the rune rows
did before RM-1085". MEASURED: it does not. _ubSpellRenderGrid builds the
grid ONCE (dataset.wired) and a pick only rewrites the two slot buttons'
icon / name in place (_ubSpellRenderCurrent), so the picked cell keeps
focus. test_keyboard_pick_keeps_focus_on_the_cell pins that, so a later
switch to a rebuild-on-pick grid has to carry focus the way
_ubRpCaptureFocus / _ubRpRestoreFocus do.

Defects the same measurement found, fixed here:
  - neither the slots nor the cells drew the one system focus ring
    (tokens.css --focus-ring), only the UA outline - the rune cells and the
    tree tabs draw it since RM-1084 / RM-1087;
  - the active slot (the one the next pick fills) was shown only by its
    .active border, so a screen reader heard two identical buttons. The
    slots now carry aria-pressed, kept in step by _ubSpellRenderCurrent.

The ring is RESOLVED off a probe element styled with var(--focus-ring),
never grepped; focus-visible is reached by a Shift press first, so a
programmatic focus() matches :focus-visible as a Tab would. Drive path
shared with test_user_builds_rune_tabs.py (its _open).
"""
import pytest

from tests.snapshot_panels.test_tab_bars_selected_state import _THEMES
from tests.snapshot_panels.test_user_builds_rune_tabs import _open

_CONTROLS = "#ub-sp-slot-d, #ub-sp-slot-f, #ub-sp-grid .ub-sp-cell"

_RING = """
([sel, themes]) => {
  const root = document.documentElement;
  const out = {};
  for (const t of themes) {
    if (t === 'hextech') root.removeAttribute('data-theme');
    else root.dataset.theme = t;
    const probe = document.createElement('div');
    probe.style.boxShadow = 'var(--focus-ring)';
    document.body.appendChild(probe);
    const ring = getComputedStyle(probe).boxShadow;
    probe.remove();
    out[t] = {
      ring,
      controls: Array.from(document.querySelectorAll(sel)).map((el) => {
        el.focus();
        const cs = getComputedStyle(el);
        const row = {
          key: el.id || ('spell ' + el.dataset.spellId),
          focused: el === document.activeElement,
          visible: el.matches(':focus-visible'),
          outline: cs.outlineStyle,
          shadow: cs.boxShadow,
        };
        el.blur();
        row.idleShadow = getComputedStyle(el).boxShadow;
        return row;
      }),
    };
  }
  root.removeAttribute('data-theme');
  return out;
}
"""

_STATE = """
() => {
  const a = document.activeElement;
  const slot = (s) => {
    const el = document.getElementById('ub-sp-slot-' + s);
    return {
      pressed: el.getAttribute('aria-pressed'),
      active: el.classList.contains('active'),
      value: document.getElementById('ub-f-spell-' + s).value,
    };
  };
  return {
    activeTag: a ? a.tagName : null,
    activeSpell: a && a.dataset ? (a.dataset.spellId || null) : null,
    activeId: a ? (a.id || null) : null,
    d: slot('d'),
    f: slot('f'),
  };
}
"""


def _cell(page, spell_id):
    return f"#ub-sp-grid .ub-sp-cell[data-spell-id='{spell_id}']"


@pytest.fixture(scope="module")
def probed(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        page.wait_for_selector("#ub-sp-grid .ub-sp-cell", timeout=5_000)
        before = page.evaluate(_STATE)
        # Pick a spell neither slot holds, from the keyboard: focus the
        # cell, then Enter (a native button turns Enter into a click).
        ids = page.eval_on_selector_all(
            "#ub-sp-grid .ub-sp-cell", "els => els.map(e => e.dataset.spellId)",
        )
        held = {before["d"]["value"], before["f"]["value"]}
        pick = next(i for i in ids if i not in held)
        page.keyboard.press("Shift")
        page.focus(_cell(page, pick))
        page.keyboard.press("Enter")
        after_pick = page.evaluate(_STATE)
        # Then activate the D slot from the keyboard (Space on a button).
        page.focus("#ub-sp-slot-d")
        page.keyboard.press("Space")
        after_slot = page.evaluate(_STATE)
        page.keyboard.press("Shift")
        ring = page.evaluate(_RING, [_CONTROLS, _THEMES])
    finally:
        page.close()
        ctx.close()
    return {
        "errors": errors,
        "pick": pick,
        "before": before,
        "after_pick": after_pick,
        "after_slot": after_slot,
        "ring": ring,
    }


def test_rendered_without_errors(probed):
    assert not probed["errors"], probed["errors"][:3]


def test_keyboard_pick_fills_the_active_slot(probed):
    b, a = probed["before"], probed["after_pick"]
    assert b["d"]["active"] and not b["f"]["active"], b
    assert a["d"]["value"] == probed["pick"], a
    # The pick flips the active slot so two picks fill both.
    assert a["f"]["active"] and not a["d"]["active"], a


def test_keyboard_pick_keeps_focus_on_the_cell(probed):
    a = probed["after_pick"]
    assert a["activeTag"] == "BUTTON", a
    assert a["activeSpell"] == probed["pick"], a


def test_keyboard_slot_activation_keeps_focus_on_the_slot(probed):
    s = probed["after_slot"]
    assert s["activeId"] == "ub-sp-slot-d", s
    assert s["d"]["active"] and not s["f"]["active"], s


@pytest.mark.parametrize("stage", ["before", "after_pick", "after_slot"])
def test_slots_announce_which_one_the_next_pick_fills(probed, stage):
    st = probed[stage]
    for s in ("d", "f"):
        want = "true" if st[s]["active"] else "false"
        assert st[s]["pressed"] == want, (stage, s, st[s])
    assert {st["d"]["pressed"], st["f"]["pressed"]} == {"true", "false"}, st


def test_every_control_was_probed(probed):
    for theme, d in probed["ring"].items():
        keys = [c["key"] for c in d["controls"]]
        assert "ub-sp-slot-d" in keys and "ub-sp-slot-f" in keys, (theme, keys)
        assert sum(k.startswith("spell ") for k in keys) >= 10, (theme, keys)


@pytest.mark.parametrize("theme", _THEMES)
def test_focused_spell_control_draws_the_system_focus_ring(probed, theme):
    d = probed["ring"][theme]
    ring = d["ring"]
    assert ring not in ("", "none"), f"{theme}: --focus-ring resolved {ring!r}"
    for c in d["controls"]:
        tag = f"{theme}: {c['key']}"
        assert c["focused"] and c["visible"], f"{tag}: not :focus-visible"
        assert c["outline"] == "none", f"{tag}: outline {c['outline']!r}"
        assert c["shadow"] == ring, f"{tag}: shadow {c['shadow']!r} != ring {ring!r}"


@pytest.mark.parametrize("theme", _THEMES)
def test_unfocused_spell_control_draws_no_ring(probed, theme):
    for c in probed["ring"][theme]["controls"]:
        assert c["idleShadow"] == "none", (
            f"{theme}: {c['key']} idle shadow {c['idleShadow']!r}"
        )
