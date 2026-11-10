"""
tests/snapshot_panels/test_settings_spend_gate_residue.py
RM-1205 (s144 uiux): the residue RM-1204's verifier logged against the
Settings API SPEND GATES list (web/js/panels/dev.js renderSpendGates), plus
one STRUCTURE defect found while measuring it.

Measured in headless Chromium under /?ui_mock=1#settings, before the fix:
- a failed refresh (GET /api/spend/gates network error, non-ok status or a
  body with no `gates`) was swallowed with no repaint and no hint, so after a
  failed toggle the box kept an unsaved optimistic state that read as saved,
  and a failed FIRST load left an empty list with no word of why;
- when the focused gate's key was missing from the new payload, keyboard
  focus fell to <body> (no fallback to the neighbouring row);
- a render already in flight when a gate was toggled (the Settings-show GET)
  could land between the optimistic flip and the POST and repaint the old
  state over the operator's click;
- `#spend-gates-list { display: flex }` (web/css/panels/header.css) beats the
  UA `[hidden]` rule, and every Settings show calls renderSpendGates(), so
  with Dev mode OFF the kill-switch rows were fetched AND displayed - the
  lane doc's STRUCTURE trap (a bare display beats [hidden]).
"""
import json

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_settings_spend_gate_focus import (
    _FOCUS,
    _close,
    _focus_gate,
    _gates,
    _wait_rebuilt,
)

VP = {"width": 1920, "height": 920}


class _Server:
    """Stateful stand-in for GET /api/spend/gates + POST /api/coach/toggle."""

    def __init__(self):
        self.vision_disabled = True
        self.gates_mode = "ok"  # "ok" | "abort" | "500" | "nogates"
        self.drop = set()  # gate keys missing from the payload
        self.hold_gets = False
        self.hold_posts = False
        self.pending_gets = []
        self.pending_posts = []
        self.gets = 0
        self.posts = []

    def body(self, vision_disabled=None):
        vd = self.vision_disabled if vision_disabled is None else vision_disabled
        j = _gates(vd)
        for k in self.drop:
            j["gates"].pop(k, None)
            j["per_match"].pop(k, None)
        return json.dumps(j)

    def gates(self, route):
        self.gets += 1
        if self.hold_gets:
            self.pending_gets.append(route)
            return
        if self.gates_mode == "abort":
            route.abort()
        elif self.gates_mode == "500":
            route.fulfill(status=500, content_type="application/json", body="{}")
        elif self.gates_mode == "nogates":
            route.fulfill(status=200, content_type="application/json", body="{}")
        else:
            route.fulfill(status=200, content_type="application/json", body=self.body())

    def toggle(self, route):
        body = json.loads(route.request.post_data or "{}")
        self.posts.append(body)
        if self.hold_posts:
            self.pending_posts.append((route, body))
            return
        self.apply(route, body)

    def apply(self, route, body):
        if body.get("mode") == "vision":
            self.vision_disabled = bool(body.get("disabled"))
        route.fulfill(status=200, content_type="application/json", body="{}")


def _open(pw_browser, mock_server, srv=None, dev_on=True):
    mock_server._store["data"] = {}
    srv = srv or _Server()
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VP)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(
        "try { localStorage.setItem('rc-dev-mode', %s); } catch (e) {}"
        % ("'1'" if dev_on else "'0'")
    )
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
    assert page.is_checked("#set-dev-mode") is dev_on
    if dev_on and srv.gates_mode == "ok" and not srv.hold_gets:
        page.wait_for_selector("#spend-gates-list .spend-gate-row", timeout=10_000)
    page.wait_for_timeout(300)
    return ctx, page, errors, srv


_HINT = """
() => {
  const host = document.getElementById('spend-gates-list');
  const h = host.querySelector('.spend-gates-stale');
  if (!h) return {stale: host.dataset.stale || null, text: null};
  const cs = getComputedStyle(h);
  return {
    stale: host.dataset.stale || null, text: h.textContent,
    role: h.getAttribute('role'), shown: h.getClientRects().length > 0,
    fs: parseFloat(cs.fontSize),
  };
}
"""


# Contrast of the hint ink on the first ancestor with an opaque background,
# both resolved through a canvas pixel (themes.css declares some surfaces as
# oklch(), so a parsed computed string is not enough - lane doc trap 3).
_HINT_CONTRAST = """
() => {
  const h = document.querySelector('#spend-gates-list .spend-gates-stale');
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', {willReadFrequently: true});
  const px = (c) => { cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000';
    cx.fillStyle = c; cx.fillRect(0, 0, 1, 1);
    return Array.from(cx.getImageData(0, 0, 1, 1).data); };
  let el = h.parentElement, bg = null, owner = null;
  while (el) {
    const p = px(getComputedStyle(el).backgroundColor);
    if (p[3] === 255) { bg = p; owner = el.id || el.className; break; }
    el = el.parentElement;
  }
  const fg = px(getComputedStyle(h).color);
  const lum = (p) => { const c = p.slice(0, 3).map((v) => { v /= 255;
    return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
  const [a, b] = [lum(fg), lum(bg)].sort((x, y) => y - x);
  return {ratio: (a + 0.05) / (b + 0.05), fg, bg, owner};
}
"""


def _render(page):
    page.evaluate(
        "async () => { const m = await import('/js/panels/dev.js');"
        " m.renderSpendGates(); }"
    )


def _wait_for(page, pred, what, timeout=5_000):
    try:
        page.wait_for_function(pred, timeout=timeout)
    except Exception as exc:  # name what never happened
        raise AssertionError(what) from exc


def test_dev_mode_off_hides_the_kill_switch_rows(mock_server, pw_browser):
    ctx, page, errors, srv = _open(pw_browser, mock_server, dev_on=False)
    try:
        st = page.evaluate(
            "() => { const h = document.getElementById('spend-gates-list');"
            " return {hidden: h.hidden, display: getComputedStyle(h).display,"
            " rows: h.querySelectorAll('.spend-gate-row').length,"
            " shown: [...h.querySelectorAll('input')].filter("
            "   e => e.getClientRects().length > 0).length}; }"
        )
        assert st["hidden"] is True, st
        assert st["display"] == "none", f"hidden list still displayed: {st}"
        assert st["shown"] == 0, f"kill-switch boxes visible with Dev mode off: {st}"
        assert srv.gets == 0, f"Dev mode off still fetched the gates {srv.gets}x"
        # Turning Dev mode on reveals and fills it.
        page.click("#set-dev-mode")
        page.wait_for_selector("#spend-gates-list .spend-gate-row", timeout=10_000)
        assert page.evaluate(
            "() => getComputedStyle(document.getElementById('spend-gates-list')).display"
        ) == "flex"
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


def test_failed_refresh_after_a_toggle_says_so_and_keeps_focus(mock_server, pw_browser):
    ctx, page, errors, srv = _open(pw_browser, mock_server)
    try:
        assert page.evaluate(_HINT)["text"] is None
        srv.gates_mode = "abort"
        h = _focus_gate(page, "Vision")
        page.keyboard.press("Space")
        _wait_for(
            page,
            "() => !!document.querySelector('#spend-gates-list .spend-gates-stale')",
            "a failed refresh after a toggle showed no degraded hint",
        )
        hint = page.evaluate(_HINT)
        assert hint["stale"] == "1", hint
        assert hint["role"] == "status", hint
        assert hint["shown"] is True, hint
        assert hint["fs"] >= 16, f"hint below the --fs-xs floor: {hint}"
        assert "out of date" in hint["text"], hint
        c = page.evaluate(_HINT_CONTRAST)
        assert c["ratio"] >= 4.5, f"hint {c['ratio']:.2f}:1 on {c['owner']}: {c}"
        # The rows were not rebuilt, so focus stays on the same box.
        assert h.evaluate("e => e.isConnected && document.activeElement === e")
        # A good refresh clears the hint.
        srv.gates_mode = "ok"
        _render(page)
        _wait_rebuilt(page, h, "the recovery render")
        hint = page.evaluate(_HINT)
        assert hint == {"stale": None, "text": None}, hint
        f = page.evaluate(_FOCUS)
        assert f["gate"] == "Vision" and f["checked"] is True, f
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


def test_failed_first_load_says_unavailable(mock_server, pw_browser):
    for mode in ("abort", "500", "nogates"):
        srv = _Server()
        srv.gates_mode = mode
        ctx, page, errors, srv = _open(pw_browser, mock_server, srv=srv)
        try:
            _wait_for(
                page,
                "() => !!document.querySelector('#spend-gates-list .spend-gates-stale')",
                f"a failed first load ({mode}) left an empty list with no hint",
            )
            hint = page.evaluate(_HINT)
            assert "unavailable" in hint["text"], (mode, hint)
            assert page.evaluate(
                "() => document.querySelectorAll('#spend-gates-list .spend-gates-stale').length"
            ) == 1, f"{mode}: hint duplicated across two failed renders"
        finally:
            _close(ctx, page)
        assert not errors, f"JS errors ({mode}): {errors[:3]}"


def test_focus_falls_to_the_neighbour_when_its_gate_vanishes(mock_server, pw_browser):
    ctx, page, errors, srv = _open(pw_browser, mock_server)
    try:
        h = _focus_gate(page, "Vision")
        srv.drop = {"vision"}
        _render(page)
        _wait_rebuilt(page, h, "the render without the vision gate")
        f = page.evaluate(_FOCUS)
        assert f["gate"] == "ARAM coach", f"focus fell to {f}"
        # No gates left at all: focus lands on the Dev mode toggle that owns
        # the list, never on <body>.
        h2 = page.evaluate_handle("() => document.activeElement")
        srv.drop = {"vision", "aram"}
        _render(page)
        _wait_rebuilt(page, h2, "the render with no gates")
        f = page.evaluate(_FOCUS)
        assert f["id"] == "set-dev-mode", f"focus fell to {f}"
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"


def test_an_inflight_render_cannot_undo_the_optimistic_flip(mock_server, pw_browser):
    ctx, page, errors, srv = _open(pw_browser, mock_server)
    try:
        # A Settings-show style render goes out first and hangs...
        srv.hold_gets = True
        _render(page)
        for _ in range(100):
            if srv.pending_gets:
                break
            page.wait_for_timeout(20)
        assert len(srv.pending_gets) == 1
        # ...then the operator toggles Vision on; the POST hangs too.
        srv.hold_posts = True
        h = _focus_gate(page, "Vision")
        page.keyboard.press("Space")
        for _ in range(100):
            if srv.pending_posts:
                break
            page.wait_for_timeout(20)
        assert len(srv.pending_posts) == 1
        assert h.evaluate("e => e.checked") is True
        # The old GET lands now, carrying the pre-click state.
        srv.pending_gets.pop(0).fulfill(
            status=200, content_type="application/json",
            body=srv.body(vision_disabled=True),
        )
        page.wait_for_timeout(400)
        assert h.evaluate("e => e.isConnected") is True, (
            "an in-flight render rebuilt the list over the click"
        )
        assert h.evaluate("e => e.checked") is True, (
            "an in-flight render repainted the pre-click state"
        )
        # The POST lands and the toggle's own render paints server truth.
        srv.hold_gets = False
        route, body = srv.pending_posts.pop(0)
        srv.apply(route, body)
        _wait_rebuilt(page, h, "the toggle's own render")
        f = page.evaluate(_FOCUS)
        assert f["gate"] == "Vision" and f["checked"] is True, f
        assert srv.vision_disabled is False
    finally:
        srv.hold_gets = False
        for r in srv.pending_gets:
            r.abort()
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"
