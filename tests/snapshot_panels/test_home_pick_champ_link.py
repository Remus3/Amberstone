"""
tests/snapshot_panels/test_home_pick_champ_link.py
RM-1545 (s144 uiux) - the Home Tonight's Pick champion name is a real,
keyboard-reachable control with the hit floor, sized to its text, and it
keeps focus across the Home tick.

THE DEFECT. MEASURED in headless Chromium under /?ui_mock=1#home before the
fix: #home-coach-pick-champ (web/index.html) was a bare <span> carrying a
click listener (web/js/main.js _homeRenderCoach) that routes to History
filtered by the champion. It had no tabindex and no role, so Tab never
reached it and Enter / Space did nothing: the deep link was mouse-only. It
was 35 px tall (under the 42 px --hit-min floor) and, as a stretched flex
child of the meta column, its click box was the whole column width (543 px
for "Vi" at 1920), so a click on the empty space beside the name opened
History. _homeRenderCoach also re-wired it by cloneNode-and-replace on every
render, and Home re-renders on a 20 s tick (_HOME.intervalMs), so even a
focused name would have been destroyed under the keyboard (lane doc trap 2).

THE FIX. The name is a <button type="button"> (web/index.html) wired ONCE
(the champion rides data-champion and an aria-label naming the action), so
the tick only rewrites its text; it hugs its text (align-self: flex-start,
max-width 100%), carries min-height: var(--hit-min) with a negative block
margin that hands the extra height back (so nothing around it moves), and
a :focus-visible ring (web/css/panels/home.css).

What is checked: the name is a focusable button; Enter and Space each route
to #history and stash the champion for the History focus; the box is at
least --hit-min tall and no wider than its text; a click beside the name
does not navigate; after a 20 s tick that changes the pick, focus is still
on the name and Enter stashes the NEW champion; the card and column heights
at 1920x920, 923x1280, 640x307 and 320x256 are the same with the hit box and
with it taken off (every host), and are the pre-fix values (Windows, where
they were measured; RM-1657).
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "web" / "data" / "ui_mock" / "home.json"

_DESKTOP = (1920, 920)
_COMPANION = (923, 1280)


def _open(pw_browser, mock_server, vp, champion=None, clock=False, mock=True):
    from tests.snapshot_panels.conftest import _WS_STUB
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]})
    page = ctx.new_page()
    if clock:
        page.clock.install()
    page.add_init_script(_WS_STUB)
    # Record every History stash: History consumes and removes the key when
    # it renders, so the test reads the log, not the key.
    page.add_init_script("""
      (() => {
        window.__stashes = [];
        const orig = Storage.prototype.setItem;
        Storage.prototype.setItem = function (k, v) {
          if (k === 'rc-history-focus-champion') window.__stashes.push(String(v));
          return orig.apply(this, arguments);
        };
      })();
    """)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    if champion:
        payload["tonight_pick"]["champion"] = champion
    state = {"body": json.dumps(payload)}

    def _fulfill(r):
        r.fulfill(status=200, content_type="application/json", body=state["body"])
    page.route("**/data/ui_mock/home.json", _fulfill)
    page.route("**/api/home/summary", _fulfill)
    mock_server._store["data"] = {}
    page.goto(mock_server.url + ("/?ui_mock=1#home" if mock else "/#home"),
              wait_until="domcontentloaded", timeout=15_000)
    _wait_name(page, payload["tonight_pick"]["champion"])
    return ctx, page, errors, payload, state


def _wait_name(page, name):
    page.wait_for_function(
        "(n) => { const e = document.getElementById('home-coach-pick-champ');"
        " return e && e.textContent.trim() === n; }",
        arg=name, timeout=10_000)


_BOX = """
() => {
  const e = document.getElementById('home-coach-pick-champ');
  const meta = e.closest('.home-coach-pick-meta').getBoundingClientRect();
  const r = e.getBoundingClientRect();
  const range = document.createRange();
  range.selectNodeContents(e);
  const t = range.getBoundingClientRect();
  const hit = parseFloat(getComputedStyle(document.documentElement)
    .getPropertyValue('--hit-min'));
  const card = document.getElementById('home-coach-pick').getBoundingClientRect();
  const reason = document.getElementById('home-coach-pick-reason').getBoundingClientRect();
  return {reasonTop: Math.round((reason.top - card.top) * 2) / 2,
          tag: e.tagName, type: e.getAttribute('type'), tabIndex: e.tabIndex,
          label: e.getAttribute('aria-label') || '', w: r.width, h: r.height,
          textW: t.width, l: r.left, r: r.right, t: r.top, b: r.bottom,
          metaR: meta.right, metaH: Math.round(meta.height), hit,
          cardH: Math.round(document.getElementById('home-coach-pick')
            .getBoundingClientRect().height)};
}
"""


def _close(ctx, page, errors):
    page.close()
    ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_the_name_is_a_focusable_button_with_an_action_label(mock_server, pw_browser):
    ctx, page, errors, payload, _ = _open(pw_browser, mock_server, _DESKTOP)
    try:
        b = page.evaluate(_BOX)
        name = payload["tonight_pick"]["champion"]
        assert b["tag"] == "BUTTON" and b["type"] == "button", b
        assert b["tabIndex"] >= 0, b
        assert b["label"].startswith(name) and "History" in b["label"], (
            f"the accessible name must start with the visible name and say"
            f" where it goes: {b['label']!r}")
    finally:
        _close(ctx, page, errors)


@pytest.mark.parametrize("key", ["Enter", " "], ids=["enter", "space"])
def test_the_keyboard_opens_history_for_the_pick(mock_server, pw_browser, key):
    ctx, page, errors, payload, _ = _open(pw_browser, mock_server, _DESKTOP)
    try:
        page.focus("#home-coach-pick-champ")
        assert page.evaluate(
            "document.activeElement && document.activeElement.id") == "home-coach-pick-champ"
        page.keyboard.press(key)
        page.wait_for_function("location.hash === '#history'", timeout=5_000)
        assert page.evaluate("window.__stashes") == [payload["tonight_pick"]["champion"]]
    finally:
        _close(ctx, page, errors)


@pytest.mark.parametrize("vp", [_DESKTOP, _COMPANION], ids=lambda v: f"{v[0]}x{v[1]}")
@pytest.mark.parametrize("champion", ["Vi", "Jinx", "Nunu & Willump"])
def test_the_hit_box_meets_the_floor_and_hugs_the_name(mock_server, pw_browser, vp, champion):
    ctx, page, errors, _, _ = _open(pw_browser, mock_server, vp, champion=champion)
    try:
        b = page.evaluate(_BOX)
        assert b["hit"] >= 42, b
        assert b["h"] >= b["hit"] - 0.5, f"{vp} {champion}: {b['h']} px tall < --hit-min"
        assert b["w"] <= b["textW"] + 2, (
            f"{vp} {champion}: the click box ({b['w']} px) is wider than the"
            f" name ({b['textW']} px)")
        # A click on the empty space beside a short name does not navigate.
        if b["metaR"] - b["r"] > 20:
            page.mouse.click(b["r"] + 10, (b["t"] + b["b"]) / 2)
            page.wait_for_timeout(300)
            assert page.evaluate("location.hash") == "#home"
            assert page.evaluate("window.__stashes") == []
    finally:
        _close(ctx, page, errors)


def test_focus_survives_the_home_tick_and_follows_the_new_pick(mock_server, pw_browser):
    ctx, page, errors, payload, state = _open(
        pw_browser, mock_server, _DESKTOP, clock=True, mock=False)
    try:
        page.focus("#home-coach-pick-champ")
        payload["tonight_pick"]["champion"] = "Heimerdinger"
        state["body"] = json.dumps(payload)
        page.clock.run_for(21_000)
        _wait_name(page, "Heimerdinger")
        assert page.evaluate(
            "document.activeElement && document.activeElement.id") == "home-coach-pick-champ", (
            "the Home tick threw keyboard focus off the champion name")
        label = page.get_attribute("#home-coach-pick-champ", "aria-label") or ""
        assert label.startswith("Heimerdinger"), label
        page.keyboard.press("Enter")
        page.wait_for_function("location.hash === '#history'", timeout=5_000)
        assert page.evaluate("window.__stashes") == ["Heimerdinger"]
    finally:
        _close(ctx, page, errors)


# Measured at HEAD before RM-1545 (the 35 px span), fixture pick, by
# serving HEAD's index.html / home.css / main.js through page.route: the card
# height, the name-plus-reason column height and the reason line's offset
# from the card top. The taller hit box must not
# move anything: 1920x920 and 923x1280 card heights are also pinned by
# tests/snapshot_panels/test_home_pick_tips_narrow.py _AUTHORED; without the
# negative block margin the column grew 63 -> 70 and the card at 640x307
# 225 -> 232, at 320x256 390 -> 397.
_LAYOUT = {
    _DESKTOP: {"cardH": 132, "metaH": 63, "reasonTop": 86.5},
    _COMPANION: {"cardH": 212, "metaH": 63, "reasonTop": 86.5},
    (640, 307): {"cardH": 225, "metaH": 85, "reasonTop": 82.0},
    (320, 256): {"cardH": 390, "metaH": 107, "reasonTop": 168.0},
}

# RM-1657: the reason line joins "<reason>", "<modes>" and "best <grade>" with a
# U+00B7 middle dot (web/js/main.js _homeRenderCoach) and the RM-1078 stub font
# maps only U+0020..U+007E, so those two dots are drawn by the host's own fallback
# face (Segoe UI on Windows, read with CDP CSS.getPlatformFontsForNode; every
# other glyph in the card is the stub's). That face's line height sets the
# reason line: CI run 42136608451 read metaH 61 and reasonTop 87.5 where Windows
# reads 63 and 86.5, and a card 2 px shorter at 640x307 and 320x256. So the
# table above pins on Windows, where it was measured, and off Windows only the
# cardH that CI read equal. The claim itself, that the hit box moves nothing,
# is measured on every host against the same page with the hit box taken off.
_HOST_FREE = {_DESKTOP: ("cardH",), _COMPANION: ("cardH",)}

_NO_HIT_BOX = """
() => {
  const s = document.createElement('style');
  s.textContent = '#home-coach-pick-champ'
    + ' { min-height: 0 !important; margin-block: 0 !important; }';
  document.head.appendChild(s);
}
"""


def _pinned(vp, layout):
    if sys.platform == "win32":
        return layout
    return {k: layout[k] for k in _HOST_FREE.get(vp, ())}


@pytest.mark.parametrize("vp", list(_LAYOUT), ids=lambda v: f"{v[0]}x{v[1]}")
def test_the_taller_hit_box_moves_nothing(mock_server, pw_browser, vp):
    ctx, page, errors, _, _ = _open(pw_browser, mock_server, vp)
    try:
        b = page.evaluate(_BOX)
        got = {k: b[k] for k in _LAYOUT[vp]}
        assert b["h"] >= b["hit"] - 0.5, b
        page.evaluate(_NO_HIT_BOX)
        bare = page.evaluate(_BOX)
        # Anchor: without the floor the name is one line, shorter than --hit-min,
        # so here the floor adds height and the negative margin must hand it back.
        assert bare["h"] < bare["hit"] - 0.5, f"{vp}: the floor adds nothing here: {bare}"
        without = {k: bare[k] for k in _LAYOUT[vp]}
        assert got == without, (
            f"{vp}: the hit box moved the pick card: with it {got}, without {without}")
        assert _pinned(vp, got) == _pinned(vp, _LAYOUT[vp]), (
            f"{vp}: the pick card layout moved: {got}")
    finally:
        _close(ctx, page, errors)
