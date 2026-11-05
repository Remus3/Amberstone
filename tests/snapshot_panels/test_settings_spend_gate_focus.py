"""
tests/snapshot_panels/test_settings_spend_gate_focus.py
RM-1204 (s144 uiux): the Settings API SPEND GATES rows keep keyboard focus
and the server's truth across their rebuild.

web/js/panels/dev.js renderSpendGates() rebuilds #spend-gates-list with
host.innerHTML = "" after every gate toggle (and on every Settings show).
Measured in headless Chromium under /?ui_mock=1#settings with Dev mode on and
two synthetic gates routed in, before the fix:
- Space on a focused gate checkbox POSTed the toggle, the re-render destroyed
  the focused node and keyboard focus fell to <body>, so a keyboard user lost
  their place after every toggle (CLAUDE.md lane doc trap 2, the innerHTML
  repaint class);
- a toggle POST that failed at the network level was swallowed by
  .catch(() => {}) with no re-render, so the box kept showing a state the
  server never stored;
- two renders in flight (two quick toggles) painted in RESPONSE order, so a
  slow older GET landing last overwrote the newer rows with a stale state.

The fix keys each row by data-gate, carries focus across the rebuild by that
key (and never moves focus that was outside the list), re-renders after a
failed POST too, and drops any response older than the newest request.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

VP = {"width": 1920, "height": 920}


def _gates(vision_disabled):
    # Shape: dashboard/routes_coach.py _serve_spend_gates. Synthetic.
    return {
        "gates": {
            "aram": {
                "label": "ARAM coach",
                "explain": "Coaching calls during ARAM games",
                "disabled": False,
            },
            "vision": {
                "label": "Vision",
                "explain": "Vision reads for OCR misses",
                "disabled": vision_disabled,
            },
        },
        "per_match": {"aram": {"usd": 0.0123, "tokens": 4567, "n": 2}},
    }


class _Server:
    """Stateful stand-in for GET /api/spend/gates + POST /api/coach/toggle."""

    def __init__(self):
        self.vision_disabled = True
        self.toggle_mode = "ok"  # "ok" | "abort"
        self.hold = False
        self.pending = []
        self.posts = []

    def gates(self, route):
        if self.hold:
            self.pending.append(route)
            return
        route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(_gates(self.vision_disabled)),
        )

    def toggle(self, route):
        body = json.loads(route.request.post_data or "{}")
        self.posts.append(body)
        if self.toggle_mode == "abort":
            route.abort()
            return
        if body.get("mode") == "vision":
            self.vision_disabled = bool(body.get("disabled"))
        route.fulfill(status=200, content_type="application/json", body="{}")


def _open(pw_browser, mock_server):
    mock_server._store["data"] = {}
    srv = _Server()
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VP)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/spend/gates*", srv.gates)
    page.route("**/api/coach/toggle*", srv.toggle)
    page.goto(
        mock_server.url + "/?ui_mock=1#settings",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        "document.body.dataset.view === 'settings' && "
        "document.querySelector('#panel-visibility-card .pv-cell') !== null",
        timeout=10_000,
    )
    if not page.is_checked("#set-dev-mode"):
        page.click("#set-dev-mode")
    page.wait_for_selector("#spend-gates-list .spend-gate-row", timeout=10_000)
    # Let the Settings-show render and the Dev-mode render both land.
    page.wait_for_timeout(300)
    return ctx, page, errors, srv


# The gate checkbox whose row label reads `name` (no data-gate needed, so the
# probe works on the pre-fix DOM too).
_GATE_BOX = """
(name) => {
  for (const row of document.querySelectorAll('#spend-gates-list .spend-gate-row')) {
    const b = row.querySelector('.spend-gate-txt b');
    if (b && b.textContent === name) return row.querySelector('input[type=checkbox]');
  }
  return null;
}
"""

_FOCUS = """
() => {
  const a = document.activeElement;
  const row = a && a.closest ? a.closest('.spend-gate-row') : null;
  const b = row ? row.querySelector('.spend-gate-txt b') : null;
  return {
    tag: a ? a.tagName : null, id: a ? a.id : null,
    gate: b ? b.textContent : null,
    checked: a && a.type === 'checkbox' ? a.checked : null,
    visible: a && a.matches ? a.matches(':focus-visible') : false,
  };
}
"""


def _focus_gate(page, name):
    # One keyboard press sets keyboard modality, so .focus() matches
    # :focus-visible the way Tab traversal does.
    page.keyboard.press("Tab")
    page.evaluate(f"(name) => ({_GATE_BOX})(name).focus()", name)
    h = page.evaluate_handle(f"(name) => ({_GATE_BOX})(name)", name)
    assert page.evaluate("e => document.activeElement === e", h)
    return h


def _wait_rebuilt(page, old_handle, what):
    try:
        page.wait_for_function("e => !e.isConnected", arg=old_handle, timeout=5_000)
    except Exception as exc:  # name the missing rebuild
        raise AssertionError(f"{what}: the gate list never re-rendered") from exc


def _close(ctx, page):
    page.close()
    ctx.close()


def test_space_toggle_keeps_focus_on_the_same_gate(mock_server, pw_browser):
    ctx, page, errors, srv = _open(pw_browser, mock_server)
    try:
        h = _focus_gate(page, "Vision")
        assert h.evaluate("e => e.checked") is False
        page.keyboard.press("Space")
        _wait_rebuilt(page, h, "after Space")
        f = page.evaluate(_FOCUS)
        assert srv.posts == [{"mode": "vision", "disabled": False}], srv.posts
        assert f["gate"] == "Vision", f"focus fell to {f}"
        assert f["checked"] is True, f
        assert f["visible"] is True, f"no keyboard ring after rebuild: {f}"
        # A second Space from the restored focus toggles straight back.
        h2 = page.evaluate_handle("() => document.activeElement")
        page.keyboard.press("Space")
        _wait_rebuilt(page, h2, "after the second Space")
        f = page.evaluate(_FOCUS)
        assert f["gate"] == "Vision" and f["checked"] is False, f
        assert srv.vision_disabled is True
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


def test_rebuild_never_steals_focus_from_outside_the_list(mock_server, pw_browser):
    ctx, page, errors, _srv = _open(pw_browser, mock_server)
    try:
        page.keyboard.press("Tab")
        page.focus("#set-dev-mode")
        old = page.evaluate_handle(f"() => ({_GATE_BOX})('Vision')")
        page.evaluate(
            "async () => { const m = await import('/js/panels/dev.js');"
            " m.renderSpendGates(); }"
        )
        _wait_rebuilt(page, old, "direct render")
        f = page.evaluate(_FOCUS)
        assert f["id"] == "set-dev-mode", f"focus moved to {f}"
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


def test_failed_toggle_repaints_the_server_state(mock_server, pw_browser):
    ctx, page, errors, srv = _open(pw_browser, mock_server)
    try:
        srv.toggle_mode = "abort"
        h = _focus_gate(page, "Vision")
        page.keyboard.press("Space")
        assert h.evaluate("e => e.checked") is True  # optimistic flip
        _wait_rebuilt(page, h, "after a failed toggle POST")
        f = page.evaluate(_FOCUS)
        # The server still has the gate disabled, so the box must say so.
        assert f["gate"] == "Vision" and f["checked"] is False, f
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


def test_a_stale_response_cannot_overwrite_a_newer_render(mock_server, pw_browser):
    ctx, page, errors, srv = _open(pw_browser, mock_server)
    try:
        srv.hold = True
        call = (
            "async () => { const m = await import('/js/panels/dev.js');"
            " m.renderSpendGates(); }"
        )
        page.evaluate(call)
        for _ in range(100):
            if len(srv.pending) == 1:
                break
            page.wait_for_timeout(20)
        assert len(srv.pending) == 1, len(srv.pending)
        page.evaluate(call)
        for _ in range(100):
            if len(srv.pending) == 2:
                break
            page.wait_for_timeout(20)
        assert len(srv.pending) == 2, len(srv.pending)
        older, newer = srv.pending
        # The newer request answers first, with the gate enabled...
        newer.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(_gates(False)),
        )
        page.wait_for_function(
            f"() => {{ const b = ({_GATE_BOX})('Vision'); return b && b.checked; }}",
            timeout=5_000,
        )
        marker = page.evaluate_handle(f"() => ({_GATE_BOX})('Vision')")
        # ...then the older one lands late with the stale (disabled) state.
        older.fulfill(
            status=200, content_type="application/json",
            body=json.dumps(_gates(True)),
        )
        page.wait_for_timeout(400)
        assert page.evaluate(f"() => ({_GATE_BOX})('Vision').checked") is True, (
            "a stale response repainted the gate list"
        )
        assert marker.evaluate("e => e.isConnected") is True, (
            "a stale response rebuilt the gate list"
        )
    finally:
        srv.hold = False
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


@pytest.mark.parametrize("name", ["ARAM coach", "Vision"])
def test_rows_carry_a_stable_gate_key(mock_server, pw_browser, name):
    ctx, page, errors, _srv = _open(pw_browser, mock_server)
    try:
        key = page.evaluate(
            f"(n) => {{ const b = ({_GATE_BOX})(n);"
            " return b ? b.dataset.gate || null : null; }",
            name,
        )
        assert key == {"ARAM coach": "aram", "Vision": "vision"}[name], key
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"
