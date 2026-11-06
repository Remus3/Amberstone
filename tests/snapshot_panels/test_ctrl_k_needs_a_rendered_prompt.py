"""
tests/snapshot_panels/test_ctrl_k_needs_a_rendered_prompt.py
RM-1421 + RM-1423 (s144 uiux): Ctrl+K acts only on a prompt the
operator can see, and never behind an open modal.

web/js/main.js bound Ctrl+K / Cmd+K to "focus the prompt input" and called
preventDefault whenever #input-text existed in the DOM. #input-bar has been
display: none on every view since 2026-04-25 (web/css/panels/input_activity.css,
"Ask Agent 7 wasn't working as intended"; the element stays wired), so the
focus() was a no-op on every view while the chord was still taken from the
browser, whose own Ctrl+K (the address-bar search) died with it. Measured in
headless Chromium at 1920x920 under ?ui_mock=1 before the fix, focus on the
body: on every view below #input-text had no client rects, Ctrl+K was
defaultPrevented and focus stayed on the body. The keybinds toast (? or H)
still advertised "Ctrl+K focus prompt".

RM-1423: with the prompt given a box, Ctrl+K behind an open modal pulled
focus out of the modal to an input under its scrim.

Ruling: Ctrl+K belongs to the prompt only while the prompt is rendered (has a
client rect) and no modal or menu is rendered over the page (the same
_letterShortcutsYield test the letter shortcuts use, minus the typing-target
half: Ctrl+K from inside the prompt still selects it). Otherwise the chord
passes to the browser untouched. The keybinds toast lists Ctrl+K only while
the prompt is rendered. A rendered prompt keeps the old behaviour, held keys
included (test_held_key_one_action.test_a_held_ctrl_k_stays_on_the_prompt_input).
"""
import pytest

from tests.snapshot_panels.test_focus_ring_token_sites import VIEWPORTS, _new_page

VP = VIEWPORTS[0]

_VIEWS = ["home", "lobby", "session", "history", "replay", "settings",
          "champ-select", "historical-pgr", "build-insights", "user-builds"]

_CTRL_K_SPY = """() => {
  window.__ctrlK = { total: 0, prevented: 0 };
  window.addEventListener('keydown', (e) => {
    if (e.key.toLowerCase() !== 'k' || !e.ctrlKey) return;
    window.__ctrlK.total += 1;
    if (e.defaultPrevented) window.__ctrlK.prevented += 1;
  });
}"""

_PROMPT_RECTS = (
    "() => document.getElementById('input-text').getClientRects().length"
)

# #input-bar is display: none on every view; lifting the input out of it is the
# one way this fixture gives the prompt a box (as test_held_key_one_action does).
_LIFT_PROMPT = (
    "() => document.body.appendChild(document.getElementById('input-text'))"
)

_TOAST_CTRL_K_ROW = """() => {
  const t = document.getElementById('keybinds-toast');
  if (!t) return null;
  const row = Array.from(t.querySelectorAll('div'))
    .find((d) => /Ctrl/.test(d.textContent) && /prompt/.test(d.textContent));
  return row ? row.getClientRects().length : -1;
}"""


def _open_view(pw_browser, mock_server, view):
    ctx, page, errors = _new_page(pw_browser, mock_server, VP)
    page.goto(mock_server.url + f"/?ui_mock=1#{view}",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(v) => document.body.dataset.view === v", arg=view, timeout=10_000
    )
    page.evaluate(_CTRL_K_SPY)
    page.evaluate("() => document.activeElement && document.activeElement.blur()")
    return ctx, page, errors


@pytest.mark.parametrize("view", _VIEWS)
def test_ctrl_k_passes_to_the_browser_when_no_prompt_is_rendered(
    mock_server, pw_browser, view
):
    ctx, page, errors = _open_view(pw_browser, mock_server, view)
    try:
        assert page.evaluate(_PROMPT_RECTS) == 0, (
            f"#input-text is rendered on {view}; this guard's premise is gone"
        )
        page.keyboard.press("Control+k")
        got = page.evaluate("() => window.__ctrlK")
        assert got == {"total": 1, "prevented": 0}, (
            f"Ctrl+K on {view} was taken from the browser with no prompt: {got}"
        )
        assert page.evaluate("() => document.activeElement === document.body")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_ctrl_k_still_focuses_a_rendered_prompt(mock_server, pw_browser):
    ctx, page, errors = _open_view(pw_browser, mock_server, "home")
    try:
        page.evaluate(_LIFT_PROMPT)
        assert page.evaluate(_PROMPT_RECTS) > 0, "the lifted prompt has no box"
        page.keyboard.press("Control+k")
        assert page.evaluate("() => window.__ctrlK") == {"total": 1, "prevented": 1}
        assert page.evaluate("() => document.activeElement.id") == "input-text"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# RM-1427 (s150) retired the second modal, the digest popout (#digest-popout).
@pytest.mark.parametrize("modal,close_btn", [
    ("#task-modal", "#task-modal-close"),
])
def test_ctrl_k_does_not_pull_focus_out_of_an_open_modal(
    mock_server, pw_browser, modal, close_btn
):
    ctx, page, errors = _open_view(pw_browser, mock_server, "home")
    try:
        page.evaluate(_LIFT_PROMPT)
        rects = page.evaluate(
            """(s) => {
              const m = document.querySelector(s);
              m.classList.remove('hidden');
              return m.getClientRects().length;
            }""",
            modal,
        )
        assert rects > 0, f"{modal} is not rendered; the fixture is wrong"
        page.focus(close_btn)
        page.keyboard.press("Control+k")
        got = page.evaluate("() => window.__ctrlK")
        assert got == {"total": 1, "prevented": 0}, got
        inside = page.evaluate(
            "(s) => document.querySelector(s).contains(document.activeElement)",
            modal,
        )
        assert inside, "Ctrl+K moved focus out of the open modal"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("lifted", [False, True], ids=["hidden-prompt", "rendered-prompt"])
def test_the_keybinds_toast_lists_ctrl_k_only_with_a_rendered_prompt(
    mock_server, pw_browser, lifted
):
    ctx, page, errors = _open_view(pw_browser, mock_server, "home")
    try:
        if lifted:
            page.evaluate(_LIFT_PROMPT)
        page.keyboard.press("?")
        page.wait_for_function(
            "() => !!document.getElementById('keybinds-toast')", timeout=5_000
        )
        rows = page.evaluate(_TOAST_CTRL_K_ROW)
        assert rows != -1, "the toast lost its Ctrl+K row altogether"
        if lifted:
            assert rows > 0, "the toast hides Ctrl+K while the prompt is rendered"
        else:
            assert rows == 0, "the toast advertises Ctrl+K with no prompt to focus"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
