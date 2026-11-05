"""
tests/snapshot_panels/test_overlay_hotkey_hints.py

RC-HOTKEY-HINTS (MAIN ORDER 2215 item 10, RM-1272): every interactive widget in
the overlay field shows its hotkey, read from the rc-shell authority, and the hint
never breaks click-through or the combat shed. Doctrine section 11.

The acceptance is a capture read back: this file drives the real ?overlay=1 page
through the headless harness with mock data (?ui_mock=1) and reads computed styles
and the DOM. It is a MOCK capture; nothing here launches the shell, the game or a
service. The live half is a row for docs/LIVE_GAME_GATED_SYNC.md.

Shapes, cited from the code the page runs:
- web/js/lib/overlay_hotkeys.js WIDGET_HOTKEYS / HOTKEY_DEFAULTS /
  hydrateOverlayHotkeys, and window.rcShell.getOverlayHotkeys
  (rc-shell/src/preload.js), answered by overlay_state.overlayHotkeyMap.
- web/js/lib/overlay_layout.js _internals._registry / LAUNCHER, and the
  .ovx-hotkey-hint child _placeAll maintains.
- web/js/panels/coach_choices.js renderCoachChoices, the per-chip .rc-hotkey pill.
- rc-shell/src/clickthrough_zones.js ZONE_SELECTOR: what the shell treats as
  interactive; the detector below is the same set plus plain controls.
"""
import json
import re
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_overlay_view import SCREENSHOTS, _open_overlay

ROOT = Path(__file__).resolve().parent.parent.parent
SHELL_STATE = ROOT / "rc-shell" / "src" / "overlay_state.js"
SHELL_TOGGLE = ROOT / "rc-shell" / "src" / "overlay_toggle.js"
LISTENER = ROOT / "tools" / "hotkey_listener.py"
HOTKEYS_JS = ROOT / "web" / "js" / "lib" / "overlay_hotkeys.js"

# A widget is interactive when it accepts input beyond its drag handle. A guard's
# name is not its domain, so this reads the rendered field instead of trusting the
# WIDGET_HOTKEYS list it is checking.
_READ_INTERACTIVE = """
async () => {
  const L = await import('/js/lib/overlay_layout.js');
  const out = {};
  const ws = L._internals._registry().concat([L._internals.LAUNCHER]);
  for (const w of ws) {
    const el = document.querySelector(w.sel);
    if (!el) continue;
    const ctl = [...el.querySelectorAll(
      'button, input, select, textarea, a[href], [data-rc-zone]')]
      .filter((n) => !n.closest('.ovx-handle'));
    const hint = el.querySelector(':scope > .ovx-hotkey-hint');
    out[w.id] = {
      interactive: ctl.length > 0 || el.matches('[data-rc-zone]'),
      painting: getComputedStyle(el).display !== 'none',
      hint: hint ? hint.textContent : null,
      key: hint ? hint.dataset.ovxHotkey : null,
    };
  }
  return out;
}
"""

_READ_HINT = """
(el) => {
  const cs = getComputedStyle(el);
  const b = el.getBoundingClientRect();
  return {
    text: el.textContent,
    display: cs.display,
    visibility: cs.visibility,
    pointerEvents: cs.pointerEvents,
    fontPx: parseFloat(cs.fontSize),
    color: cs.color,
    animation: cs.animationName,
    w: b.width, h: b.height, x: b.x, y: b.y,
  };
}
"""


def _authority():
    """The bindings as the authorities spell them, read off disk."""
    state = SHELL_STATE.read_text(encoding="utf-8")
    toggle = SHELL_TOGGLE.read_text(encoding="utf-8")

    def _key(name, text=state):
        m = re.search(rf'\b{name}:\s*"([^"]+)"', text)
        assert m, f"{name} not found in the authority"
        return m.group(1)

    return {
        "active": _key("hotkeyActive"),
        "cycle": _key("hotkeyCycleInGame"),
        "visible": _key("hotkey", toggle),
        "hide": _key("hotkeyToggle"),
        "reset": _key("hotkeyReset"),
    }


def _mirror():
    """The page's fallback map (used when the shell has no bridge), off disk."""
    src = HOTKEYS_JS.read_text(encoding="utf-8")
    block = re.search(r"HOTKEY_DEFAULTS = Object\.freeze\(\{(.*?)\}\)", src, re.S)
    assert block, "HOTKEY_DEFAULTS missing"
    return dict(re.findall(r'(\w+):\s*"([^"]+)"', block.group(1)))


def test_fallback_map_equals_the_shell_authority():
    assert _mirror() == _authority()


def test_ingame_bindings_are_the_ones_the_win32_listener_owns():
    """Electron globalShortcut is dead while League holds focus, so a hint naming
    an in-game key has to name one tools/hotkey_listener.py actually claims."""
    src = LISTENER.read_text(encoding="utf-8")
    hot = re.search(r"_HOTKEYS = \((.*?)^\)", src, re.S | re.M)
    assert hot, "_HOTKEYS tuple missing from the listener"
    for name, letter in (("active", "A"), ("cycle", "B"), ("visible", "O")):
        assert _authority()[name] == f"Ctrl+Shift+{letter}", name
        assert f"_VK_{letter})" in hot.group(1), f"listener does not claim {letter}"


@pytest.mark.parametrize("mode", ["sr", "aram", "arena", "tft"])
def test_every_interactive_widget_shows_its_hotkey(mode, mock_server, pw_browser):
    """The ACCEPT line, per game family fixture. Reads the field; a widget with
    controls and no hint fails, whichever list it was left off."""
    want = _authority()
    ctx, page, errors = _open_overlay(
        pw_browser, mock_server, query=f"?ui_mock=1&mode={mode}&overlay=1"
    )
    try:
        page.wait_for_selector("#w-launcher > .ovx-hotkey-hint", state="attached", timeout=5_000)
        if mode != "tft":
            page.wait_for_selector("#ovset #ovset-panelset", state="attached", timeout=10_000)
            # Fill the data-gated chip mount so w-choices is on the field too.
            page.evaluate(
                """async () => {
                    const C = await import('/js/panels/coach_choices.js');
                    C.renderCoachChoices({coach: {choices: [
                        {key: 'A', label: 'Trade', confidence: 'high'},
                        {key: 'B', label: 'Back off', confidence: 'mid'}]}});
                    const L = await import('/js/lib/overlay_layout.js');
                    L.placeOverlayField();
                }"""
            )
        field = page.evaluate(_READ_INTERACTIVE)
        interactive = {w for w, r in field.items() if r["interactive"]}
        # Non-vacuous: the set the doctrine names really is on this page.
        league = {"w-launcher", "w-choices", "w-build", "w-ovds"}
        assert (league if mode != "tft" else {"w-launcher"}) <= interactive, field
        for wid in interactive:
            assert field[wid]["hint"] == want[field[wid]["key"]], f"{wid}: {field[wid]}"
        # And the inverse: a display-only widget on the field carries no reminder
        # (rule 8). An interactive widget that is empty or off the field holds its
        # hint unseen, which is the point of the no-reflow child.
        for wid in set(field) - interactive:
            if field[wid]["painting"]:
                assert field[wid]["hint"] is None, f"{wid} is display-only: {field[wid]}"
        # Each hint is actually readable, not just present.
        sels = {"w-launcher": "#w-launcher", "w-choices": "#rn-choices",
                "w-build": "#view-active-match .am-pane-build", "w-ovds": "#am-pane-ovds"}
        for wid in ({"w-launcher"} if mode == "tft" else league):
            read = page.eval_on_selector(f"{sels[wid]} > .ovx-hotkey-hint", _READ_HINT)
            assert read["display"] != "none" and read["visibility"] == "visible", (wid, read)
            assert read["w"] > 0 and read["h"] > 0, (wid, read)
            assert read["text"].isascii(), (wid, read)
        if mode != "tft":
            # The per-chip pick keys stay on every chip (doctrine section 6).
            pills = page.eval_on_selector_all(
                "#rn-choices .rc-chip .rc-hotkey",
                "els => els.map(e => [e.textContent, getComputedStyle(e).display])",
            )
            assert [p[0] for p in pills] == ["Alt+1", "Alt+2"], pills
            assert all(p[1] != "none" for p in pills), pills
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [hints {mode}]: {errors[:3]}"


def test_field_init_hydrates_from_the_shell(mock_server, pw_browser):
    """The default path: a shell bridge present at boot, nothing called by hand.
    The test above drives the map; this one drives initOverlayLayout's own wire."""
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(
        "window.rcShell = {getOverlayHotkeys: async () => ({active: 'Ctrl+Alt+Q'})};"
    )
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=sr&overlay=1",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(document.querySelector('#w-launcher > .ovx-hotkey-hint') || {}).textContent"
            " === 'Ctrl+Alt+Q'",
            timeout=10_000,
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [init hydrate]: {errors[:3]}"


def test_a_registered_widget_names_its_hotkey(mock_server, pw_browser):
    """registerOverlayWidget is the TFT-14 planner's hook; an extra with controls
    declares its reminder, and an unknown action gets none."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        result = page.evaluate(
            """async () => {
                const L = await import('/js/lib/overlay_layout.js');
                const add = (id, hotkey) => {
                    const m = document.createElement('div');
                    m.id = id.slice(2);
                    document.body.appendChild(m);
                    L.registerOverlayWidget({id, sel: '#' + m.id, x: 900, y: 500, hotkey});
                    const h = m.querySelector(':scope > .ovx-hotkey-hint');
                    return h ? h.textContent : null;
                };
                return [add('w-extra-a', 'cycle'), add('w-extra-b', 'nope')];
            }"""
        )
        assert result == [_authority()["cycle"], None], result
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [extra]: {errors[:3]}"


def test_a_control_added_to_a_listed_out_widget_reddens_the_detector(mock_server, pw_browser):
    """Positive control for the guard above: the detector must SEE a new control,
    or an empty detection would pass it for ever."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.evaluate(
            "() => { const b = document.createElement('button');"
            " document.querySelector('#am-statspanel').appendChild(b); }"
        )
        field = page.evaluate(_READ_INTERACTIVE)
        assert field["w-stats"]["interactive"] is True
        assert field["w-stats"]["hint"] is None
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [control]: {errors[:3]}"


def test_hint_survives_a_renderer_rebuild(mock_server, pw_browser):
    """Renderers rebuild these mounts (innerHTML), which drops the hint exactly as
    it drops the drag handle; the place pass re-adds one, never two."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_selector("#am-pane-ovds > .ovx-hotkey-hint", state="attached", timeout=10_000)
        page.evaluate(
            """async () => {
                const L = await import('/js/lib/overlay_layout.js');
                document.querySelector('#am-pane-ovds').innerHTML = '<div>rebuilt</div>';
                L.placeOverlayField();
                L.placeOverlayField();
            }"""
        )
        assert page.locator("#am-pane-ovds > .ovx-hotkey-hint").count() == 1
        # The launcher has its own two paths: a fresh mount and a re-entry. Read
        # synchronously, in one evaluate: the debounced observer repairs a missing
        # hint 150 ms later, which let a mutant of the create path survive.
        counts = page.evaluate(
            """async () => {
                const L = await import('/js/lib/overlay_layout.js');
                const n = () => document.querySelectorAll(
                    '#w-launcher > .ovx-hotkey-hint').length;
                document.querySelector('#w-launcher > .ovx-hotkey-hint').remove();
                L._internals._ensureLauncher();
                const reentry = n();
                document.querySelector('#w-launcher').remove();
                L._internals._ensureLauncher();
                return [reentry, n()];
            }"""
        )
        assert counts == [1, 1], f"launcher hint [re-entry, fresh mount]: {counts}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [rebuild]: {errors[:3]}"


def test_hint_never_takes_a_click_and_never_grows_a_target(mock_server, pw_browser):
    """HIT-TARGETS + click-through: pointer-events none, not a zone, and the
    launcher square keeps its 34x34 box with the hint beside it."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_selector("#w-launcher > .ovx-hotkey-hint", state="attached", timeout=5_000)
        for sel in ("#w-launcher", "#view-active-match .am-pane-build"):
            hint = f"{sel} > .ovx-hotkey-hint"
            assert page.eval_on_selector(hint, _READ_HINT)["pointerEvents"] == "none", sel
            assert page.eval_on_selector(hint, "e => e.closest('[data-rc-zone]') === e") is False
            # What a press at the hint's centre lands on is never the hint.
            hit = page.eval_on_selector(
                hint,
                "e => { const b = e.getBoundingClientRect();"
                " const t = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);"
                " return !!t && !t.classList.contains('ovx-hotkey-hint'); }",
            )
            assert hit, f"{sel}: the hint took the hit test"
        box = page.locator("#w-launcher").bounding_box()
        assert box["width"] == 34 and box["height"] == 34, box
        # The menu stays closed-by-default and the launcher zone is unchanged.
        assert page.eval_on_selector("#w-launcher", "e => e.hasAttribute('data-rc-zone')")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [hit targets]: {errors[:3]}"


def test_hint_obeys_the_doctrine_tiers(mock_server, pw_browser):
    """TYPOGRAPHY + HIERARCHY: the overlay's own small token, neutral ink dimmer
    than a head, no motion, no red. Rule 3 + section 6: no text to read in a fight,
    so the widget-level hint sheds, and the chip keys stay."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_selector(
            "#view-active-match .am-pane-build > .ovx-hotkey-hint", state="attached", timeout=10_000
        )
        hint = "#view-active-match .am-pane-build > .ovx-hotkey-hint"
        read = page.eval_on_selector(hint, _READ_HINT)
        token = page.evaluate(
            "parseFloat(getComputedStyle(document.body).getPropertyValue('--fs-ov-sigil'))"
        )
        assert read["fontPx"] == token, read
        assert read["animation"] == "none", read
        assert "255, 255, 255" in read["color"], read  # --ovx-text, never a status hue
        assert "0.55" in read["color"], read
        page.evaluate("document.body.dataset.fight = '1'")
        assert page.eval_on_selector(hint, _READ_HINT)["display"] == "none", "must shed in a fight"
        assert page.eval_on_selector("#w-launcher > .ovx-hotkey-hint", _READ_HINT)["display"] == "none"
        page.evaluate("delete document.body.dataset.fight")
        assert page.eval_on_selector(hint, _READ_HINT)["display"] != "none"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [tiers]: {errors[:3]}"


def test_hint_reads_the_live_binding_from_the_bridge(mock_server, pw_browser):
    """The hint is not a literal: a binding the shell reports is what paints, so a
    future rebind reaches it. A garbage reply keeps the fallback."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_selector("#w-launcher > .ovx-hotkey-hint", state="attached", timeout=5_000)
        result = page.evaluate(
            """async () => {
                const H = await import('/js/lib/overlay_hotkeys.js');
                const L = await import('/js/lib/overlay_layout.js');
                const read = () => document.querySelector(
                    '#w-launcher > .ovx-hotkey-hint').textContent;
                const before = read();
                window.rcShell = {getOverlayHotkeys: async () => ({active: 'Ctrl+Alt+Z'})};
                const ok = await H.hydrateOverlayHotkeys();
                L.placeOverlayField();
                const rebound = read();
                window.rcShell = {getOverlayHotkeys: async () => ({active: 42, cycle: '<b>x</b>'})};
                await H.hydrateOverlayHotkeys();
                L.placeOverlayField();
                const garbage = read();
                delete window.rcShell;
                return {before, ok, rebound, garbage};
            }"""
        )
        assert result["before"] == _authority()["active"], result
        assert result["ok"] is True, result
        assert result["rebound"] == "Ctrl+Alt+Z", result
        # A non-string or unbindable value is refused, so the last good value stays.
        assert result["garbage"] == "Ctrl+Alt+Z", result
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [bridge]: {errors[:3]}"


def test_launcher_menu_lists_the_bindings(mock_server, pw_browser):
    """The ON/OFF icon is a separate window sized to the icon, so its key rides its
    tooltip and this reference block; every key an operator can press is here."""
    want = _authority()
    from tests.snapshot_panels.test_overlay_launcher_menu import _MENU_READY, _TAP_LAUNCHER

    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_selector("#w-launcher", timeout=5_000)
        assert page.evaluate(_TAP_LAUNCHER) is True
        page.wait_for_function(_MENU_READY, timeout=5_000)
        text = page.eval_on_selector(".ovx-menu-hotkeys", "e => e.textContent")
        for key in want.values():
            assert key in text, f"{key} missing from the menu reference: {text!r}"
        assert text.isascii(), text
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [menu keys]: {errors[:3]}"


_READ_HINT_AUDIT = """
() => {
  const rect = (b) => ({x: Math.round(b.x), y: Math.round(b.y),
                        r: Math.round(b.right), b: Math.round(b.bottom)});
  const out = [];
  for (const h of document.querySelectorAll('.ovx-hotkey-hint')) {
    const w = h.parentElement;
    const cs = getComputedStyle(h);
    if (cs.display === 'none' || getComputedStyle(w).display === 'none') continue;
    // The hint must not sit on the widget's own words, so measure the TEXT of
    // every other leaf it could land on, not the elements' boxes.
    const hb = h.getBoundingClientRect();
    const onText = [];
    const walk = document.createTreeWalker(w, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (h.contains(n) || !n.textContent.trim()) continue;
      const pe = getComputedStyle(n.parentElement);
      if (pe.display === 'none' || pe.visibility === 'hidden') continue;
      const r = document.createRange();
      r.selectNodeContents(n);
      for (const b of r.getClientRects()) {
        if (b.width && b.height && b.x < hb.right && hb.x < b.right
            && b.y < hb.bottom && hb.y < b.bottom) {
          onText.push(n.textContent.trim().slice(0, 24));
        }
      }
    }
    out.push({id: w.dataset.ovxId, text: h.textContent, box: rect(hb),
              font: cs.fontSize, color: cs.color, pointer: cs.pointerEvents,
              onText});
  }
  return out;
}
"""


def test_hint_audit_capture(mock_server, pw_browser):
    """The ACCEPT's read-back: the rendered hints of the League and TFT fields,
    written beside the screenshots (gitignored) and asserted. STRUCTURE: one per
    widget. TYPOGRAPHY: the token. HIT-TARGETS: pointer-events none, on screen, and
    the launcher's stays in its gap (above the ON/OFF icon at design y 72, left of
    the TFT vitals at design x 70). ASCII. HIERARCHY: it covers no widget text."""
    captures = {}
    for label, query in (("sr", "?ui_mock=1&mode=sr&overlay=1"),
                         ("aram", "?ui_mock=1&mode=aram&overlay=1"),
                         ("arena", "?ui_mock=1&mode=arena&overlay=1"),
                         ("tft", "?ui_mock=1&mode=tft&overlay=1")):
        ctx, page, errors = _open_overlay(pw_browser, mock_server, query=query)
        try:
            page.wait_for_selector("#w-launcher > .ovx-hotkey-hint", state="attached", timeout=5_000)
            if label != "tft":
                page.wait_for_selector("#am-pane-ovds > .ovx-hotkey-hint", state="attached", timeout=10_000)
            page.evaluate(
                """async () => {
                    const C = await import('/js/panels/coach_choices.js');
                    C.renderCoachChoices({coach: {choices: [
                        {key: 'A', label: 'Trade', confidence: 'high'},
                        {key: 'B', label: 'Back off', confidence: 'mid'}]}});
                    (await import('/js/lib/overlay_layout.js')).placeOverlayField();
                }"""
            )
            captures[label] = page.evaluate(_READ_HINT_AUDIT)
            # The accessibility tree reads the reminder too, not only the pixels.
            assert _authority()["active"] in page.locator(
                "#w-launcher > .ovx-hotkey-hint"
            ).aria_snapshot(), label
            SCREENSHOTS.mkdir(exist_ok=True)
            page.screenshot(path=str(SCREENSHOTS / f"overlay_hotkey_hints_{label}.png"))
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [{label}]: {errors[:3]}"
    (SCREENSHOTS / "overlay_hotkey_hints_audit.json").write_text(
        json.dumps(captures, indent=1), encoding="ascii", newline="\n"
    )
    want = _authority()["active"]
    assert {h["id"] for h in captures["sr"]} >= {"w-launcher", "w-build", "w-ovds"}, captures["sr"]
    assert {h["id"] for h in captures["tft"]} == {"w-launcher"}, captures["tft"]
    for label, hints in captures.items():
        ids = [h["id"] for h in hints]
        assert len(ids) == len(set(ids)), f"{label}: two hints on one widget: {ids}"
        for h in hints:
            where = f"{label} {h['id']}: {h}"
            assert h["text"] == want, where
            assert h["text"].isascii(), where
            assert h["font"] == "12px", where
            assert h["pointer"] == "none", where
            assert h["onText"] == [], where
            assert 0 <= h["box"]["x"] and h["box"]["r"] <= 1920, where
            assert 0 <= h["box"]["y"] and h["box"]["b"] <= 1080, where
            if h["id"] == "w-launcher":
                assert h["box"]["b"] <= 72, where
                assert h["box"]["r"] <= 70, where


def test_new_files_are_ascii_lf():
    for path in (Path(__file__), HOTKEYS_JS):
        raw = path.read_bytes()
        assert not [b for b in raw if b > 0x7F], f"non-ASCII in {path.name}"
        assert b"\r" not in raw, f"CR in {path.name}"
