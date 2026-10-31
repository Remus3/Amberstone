"""RM-1222: the Auto Accept control never shows a choice it did not save.

The defect, measured 2026-10-31 at ddb4a5e20: ``web/js/main.js``
``_setAutoAccept`` painted the new state, wrote the localStorage mirror and
sent the LCU agent ``set_config`` BEFORE it knew whether the save to
``/api/lcu/auto-accept`` (``data/auto_accept_pref.json``, the choice RC's own
ready-check loop reads) had landed, and swallowed the save's failure
(``.catch(() => {})``). A 503 from the route therefore left the control
showing - and the agent acting on - a choice that was never stored.

Ruling C (s145 Q2): save FIRST. A failed or unreachable save puts the
previous state back on both controls, leaves the mirror and the agent alone,
and tells the operator in plain words; only a saved choice is pushed to the
agent. Drives the real page in headless Chromium with the routes stubbed.
"""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent.parent

_TOAST = "#auto-accept-save-toast"


def _open(pw_browser, mock_server, pref_mode):
    """Open the mock lobby with /api/lcu/auto-accept answering per
    ``pref_mode`` ("ok", "503", "abort") and every lcu-cmd body recorded."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    order: list = []          # ("pref", body) / ("cmd", body), in arrival order
    # The polled envelope: the agent's posted config, which (RM-1222) follows
    # the saved preference. It only changes when a save lands and the agent
    # is told - exactly what the "ok" set_config stub below models.
    live = {"lcu": {"phase": "Lobby", "config": {"auto_accept": True}}}

    def _state(route, request):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(live))

    def _pref(route, request):
        if request.method != "POST":
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True, "enabled": True}))
            return
        body = json.loads(request.post_data or "{}")
        order.append(("pref", body))
        if pref_mode == "abort":
            route.abort()
        elif pref_mode == "503":
            route.fulfill(status=503, content_type="application/json",
                          body=json.dumps({"ok": False, "error": "could not "
                                           "save the auto-accept preference "
                                           "- retry"}))
        else:
            route.fulfill(status=200, content_type="application/json",
                          body=json.dumps({"ok": True,
                                           "enabled": body.get("enabled")}))

    def _cmd(route, request):
        body = json.loads(request.post_data or "{}")
        order.append(("cmd", body))
        if body.get("cmd") == "set_config" and "auto_accept" in body:
            live["lcu"]["config"]["auto_accept"] = body["auto_accept"]
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": True, "id": "stub-1"}))

    def _cmd_result(route, request):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"result": {"ok": True}}))

    ctx.route(lambda u: urlsplit(u).path == "/api/state", _state)
    ctx.route("**/api/lcu/auto-accept", _pref)
    ctx.route("**/api/lcu-cmd", _cmd)
    ctx.route("**/api/lcu-cmd-result*", _cmd_result)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    # The polled envelope carries config.auto_accept = true: wait for "On".
    page.wait_for_function(
        "document.querySelector('#lv-auto-accept') && "
        "!document.querySelector('#lv-auto-accept').disabled && "
        "document.querySelector('#lv-auto-accept-state').textContent"
        ".trim() === 'On'",
        timeout=10_000)
    return ctx, page, errors, order


def _wait_for(page, pred, secs=8.0):
    deadline = time.time() + secs
    while time.time() < deadline and not pred():
        page.wait_for_timeout(100)


def _control_state(page):
    return page.evaluate("""() => {
        const b = document.querySelector('#lv-auto-accept');
        const s = document.querySelector('#lv-auto-accept-state');
        const c = document.querySelector('#set-lobby-auto-accept');
        let mirror = null;
        try { mirror = localStorage.getItem('rc-lobby-auto-accept'); } catch (_) {}
        return {
            text: s ? s.textContent.trim() : null,
            on: b ? b.classList.contains('is-on') : null,
            checked: c ? c.checked : null,
            mirror: mirror,
        };
    }""")


def _toast(page):
    return page.evaluate("""(sel) => {
        const t = document.querySelector(sel);
        if (!t) return null;
        const cs = getComputedStyle(t);
        return {text: t.textContent.trim(), role: t.getAttribute('role'),
                shown: t.classList.contains('show'),
                opacity: cs.opacity, display: cs.display,
                visibility: cs.visibility};
    }""", _TOAST)


def _assert_failed_save_is_truthful(page, order, errors):
    _wait_for(page, lambda: any(k == "pref" for k, _ in order))
    assert [b for k, b in order if k == "pref"] == [{"enabled": False}], order
    _wait_for(page, lambda: (_toast(page) or {}).get("shown"))
    page.wait_for_timeout(1200)     # well past the old set_config moment
    st = _control_state(page)
    assert st["text"] == "On" and st["on"] is True, (
        f"the lobby toggle shows a choice that was not saved: {st}")
    assert st["checked"] is True, (
        f"the Settings checkbox shows a choice that was not saved: {st}")
    assert st["mirror"] in ("1", None), st
    assert [b for k, b in order if k == "cmd"] == [], (
        f"the agent was told an unsaved choice: {order}")
    t = _toast(page)
    assert t and t["shown"] and t["role"] == "status", t
    assert t["display"] != "none" and t["visibility"] != "hidden", t
    assert float(t["opacity"]) > 0.5, f"the notice is not visible: {t}"
    low = t["text"].lower()
    assert "auto accept" in low and "not saved" in low, t
    for raw in ("503", "error", "{", "http", "fetch"):
        assert raw not in low, f"raw error text in the notice: {t}"
    assert not errors, errors[:3]


def test_a_503_save_keeps_the_previous_state_and_says_so(mock_server,
                                                         pw_browser):
    ctx, page, errors, order = _open(pw_browser, mock_server, "503")
    try:
        page.locator("#lv-auto-accept").click()
        _assert_failed_save_is_truthful(page, order, errors)
    finally:
        page.close()
        ctx.close()


def test_an_unreachable_save_keeps_the_previous_state_and_says_so(
        mock_server, pw_browser):
    ctx, page, errors, order = _open(pw_browser, mock_server, "abort")
    try:
        page.locator("#lv-auto-accept").click()
        _assert_failed_save_is_truthful(page, order, errors)
    finally:
        page.close()
        ctx.close()


def test_a_saved_choice_shows_and_then_reaches_the_agent(mock_server,
                                                         pw_browser):
    ctx, page, errors, order = _open(pw_browser, mock_server, "ok")
    try:
        page.locator("#lv-auto-accept").click()
        _wait_for(page, lambda: any(k == "cmd" for k, _ in order))
        kinds = [k for k, _ in order]
        assert kinds[:2] == ["pref", "cmd"], (
            f"set_config must follow a landed save, not race it: {order}")
        assert order[0][1] == {"enabled": False}, order
        assert order[1][1] == {"cmd": "set_config", "auto_accept": False}, order
        st = _control_state(page)
        assert st["text"] == "Off" and st["on"] is False, st
        assert st["checked"] is False and st["mirror"] == "0", st
        t = _toast(page)
        assert t is None or not t["shown"], f"a notice on a good save: {t}"
        assert not errors, errors[:3]
    finally:
        page.close()
        ctx.close()


def test_ascii_only():
    raw = Path(__file__).read_bytes()
    assert not [b for b in raw if b > 0x7F]
