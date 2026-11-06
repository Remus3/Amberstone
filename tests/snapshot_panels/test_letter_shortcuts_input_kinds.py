"""
tests/snapshot_panels/test_letter_shortcuts_input_kinds.py
RM-1765 (s144 uiux): which INPUT owns the letter keys.

RM-1323 states the rule in web/js/main.js: a letter shortcut belongs to the
page, never to a control that reads the letter keys itself (text entry, a
<select>'s type-ahead). The yield it shipped tested the TAG, so every <input>
took the letters, including the ones that read none. Measured in headless
Chromium before this fix, with focus on a checkbox (the Settings Auto-push
runes toggle and the Replay items filter), a radio or a range (the Settings
PGR baseline slider): A did not click ANALYZE NOW, F asked for no fullscreen,
Z did not flip zen, H and ? showed no keybind toast and Shift+R did not reset
the preferences. Tick a Settings toggle from the keyboard and every shortcut
went dead until focus moved off it. The Replay player already draws the line
by input TYPE (review_player_model.js isTypingTarget, imported by main.js for
the Space rule), so the two key handlers disagreed about the same control.

The fix routes the yield through that same isTypingTarget. Pinned both ways:
- a checkbox, radio, range or button-type input lets every shortcut act,
  on synthetic hosts and on two real ones;
- every text-entry input type still takes every letter as text, and so do a
  textarea and a contenteditable host, pressed once and HELD (RM-1758 (c):
  test_held_key_one_action.py held only Z in an input; F, A, H, ? and Shift+R
  were never held in a text control).
"""
import pytest

from tests.snapshot_panels.test_hotkey_letter_owners import (
    _KEYS,
    _TYPED,
    _assert_nothing_fired,
    _baseline,
    _open,
    _press_and_assert_fired,
)

# Input types that read no letter key: Space / Enter / arrows only.
_NON_TEXT = ["checkbox", "radio", "range", "button", "submit", "reset", "color"]
# Input types a letter is typed into.
_TEXT = ["text", "search", "email", "password", "url", "tel"]


def _focus_new_input(page, kind):
    page.evaluate(
        """(kind) => {
          const i = document.createElement('input');
          i.type = kind;
          i.id = 'probe-input';
          document.body.appendChild(i);
          i.focus();
        }""",
        kind,
    )
    assert page.evaluate(
        "() => document.activeElement && document.activeElement.id"
    ) == "probe-input", f"setup: the {kind} input did not take focus"


@pytest.mark.parametrize("key", _KEYS)
@pytest.mark.parametrize("kind", _NON_TEXT)
def test_a_shortcut_acts_from_an_input_that_reads_no_letters(
    mock_server, pw_browser, kind, key
):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        _focus_new_input(page, kind)
        _press_and_assert_fired(page, key)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# Real hosts: a Settings toggle and slider, and a Replay event filter.
_REAL = {
    "settings_push_runes": ("settings", "#set-push-runes"),
    "settings_pgr_baseline": ("settings", "#set-pgr-baseline"),
    "replay_items_filter": ("replay", "#replay-evt-items"),
}


@pytest.mark.parametrize("key", ["a", "z", "h"])
@pytest.mark.parametrize("host", sorted(_REAL))
def test_a_shortcut_acts_from_a_real_toggle_or_slider(
    mock_server, pw_browser, host, key
):
    view, sel = _REAL[host]
    ctx, page, errors = _open(pw_browser, mock_server, view)
    try:
        # Some of these sit in a collapsed or unrendered group in the mock;
        # focus() is a no-op on a control with no box, so give it one.
        page.evaluate(
            """(sel) => {
              const i = document.querySelector(sel);
              if (!i.getClientRects().length) {
                i.style.position = 'fixed';
                i.style.left = '10px';
                i.style.top = '10px';
                document.body.appendChild(i);
              }
              i.focus();
            }""",
            sel,
        )
        assert page.evaluate(
            "(sel) => document.activeElement === document.querySelector(sel)", sel
        ), f"setup: {sel} did not take focus"
        checked = page.evaluate(
            "(sel) => document.querySelector(sel).checked", sel
        )
        value = page.evaluate("(sel) => document.querySelector(sel).value", sel)
        _press_and_assert_fired(page, key)
        # The letter did not change the control on its way to the page.
        assert page.evaluate(
            "(sel) => document.querySelector(sel).checked", sel
        ) == checked
        assert page.evaluate(
            "(sel) => document.querySelector(sel).value", sel
        ) == value
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("key,char", _TYPED)
@pytest.mark.parametrize("kind", _TEXT)
def test_a_letter_in_every_text_input_type_is_text(
    mock_server, pw_browser, kind, key, char
):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        _focus_new_input(page, kind)
        before = _baseline(page)
        page.keyboard.press(key)
        _assert_nothing_fired(page, before, key)
        assert page.input_value("#probe-input") == char, f"{key!r} in a {kind}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _hold(page, key, repeats=3):
    """One press plus `repeats` autorepeat keydowns (Playwright sets
    event.repeat from the second down), then the release. Shift+R holds
    Shift around the held R."""
    if key == "Shift+R":
        page.keyboard.down("Shift")
        for _ in range(repeats + 1):
            page.keyboard.down("R")
        page.keyboard.up("R")
        page.keyboard.up("Shift")
        return
    for _ in range(repeats + 1):
        page.keyboard.down(key)
    page.keyboard.up(key)


@pytest.mark.parametrize("key,char", _TYPED)
@pytest.mark.parametrize("host", ["input", "textarea", "contenteditable"])
def test_a_held_letter_in_a_text_control_types_every_repeat(
    mock_server, pw_browser, host, key, char
):
    ctx, page, errors = _open(pw_browser, mock_server, "home")
    try:
        page.evaluate(
            """(host) => {
              const d = document.createElement(
                host === 'contenteditable' ? 'div' : host);
              d.id = 'probe-text';
              if (host === 'contenteditable') d.contentEditable = 'true';
              document.body.appendChild(d);
              d.focus();
            }""",
            host,
        )
        before = _baseline(page)
        _hold(page, key)
        _assert_nothing_fired(page, before, key)
        typed = page.evaluate(
            "() => { const d = document.getElementById('probe-text');"
            " return d.value !== undefined ? d.value : d.textContent; }"
        )
        assert typed == char * 4, f"a held {key!r} in a {host} gave {typed!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
