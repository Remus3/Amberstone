"""
tests/snapshot_panels/test_overlay_view.py
Electron overlay route (HZ-D1, docs/ELECTRON_OVERLAY.md sections 6+7).

The in-game overlay window loads RC_ORIGIN/?overlay=1. main.js stamps
body[data-shell="overlay"] at module top (before the first render) and the
view router pins the active-match view unconditionally - hash / manual /
auto derivation are bypassed. web/css/overlay.css then composes a compact
single-column right-dock (~460px) over a transparent page background:
ONLY the coach CALL pane + BUILD pane (#view-active-match) plus the
callouts/lead mounts (#rn-lead / #rn-callouts inside #right-now) are
shown; header / nav / footer / every other view is display:none.

Drive path mirrors test_active_match_view.py (C2):
/?ui_mock=1&mode=sr&overlay=1. The forced applyView("active-match") fires
_amMockLoad, which fetches /data/ui_mock/active_match_sr.json and renders
the CALL pane with phase=InProgress - we wait on that #am-sub stamp.

Also covered: the .ov-pulse change-glow hook (web/js/overlay_pulse.js -
MutationObserver, throttled, overlay-only), the right-dock geometry, and
the no-overlay-param control (normal shell untouched).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

# Views that must be display:none in overlay mode (the "all other views"
# half of the contract) - a representative slice of every surface class:
# game-state views, a sticky utility view, the home overlay, and the
# bottom chrome.
_HIDDEN_SELECTORS = [
    "header",
    "footer",
    "#view-lobby",
    "#view-champ-select",
    "#view-last-match",
    "#view-settings",
    "#home-overlay",
    "#activity-strip",
    "#input-bar",
]


def _display(page, selector):
    return page.eval_on_selector(
        selector, "el => getComputedStyle(el).display"
    )


def _open_overlay(pw_browser, mock_server, query="?ui_mock=1&mode=sr&overlay=1"):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state - the overlay shell must not depend on a live
    # envelope to compose itself (the Electron window can open before
    # the first coach tick).
    mock_server._store["data"] = {}

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(mock_server.url + "/" + query,
              wait_until="domcontentloaded", timeout=15_000)
    # Wait for the ui_mock active-match fixture render to land (the
    # isLive branch stamps "phase InProgress" into #am-sub).
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    return ctx, page, errors


def test_overlay_shell_renders_compact_subset(mock_server, pw_browser):
    """?overlay=1: shell flag set, view forced to active-match, compact
    panel subset visible, header/footer/other views display:none."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        # Shell flag + forced view.
        assert page.evaluate("document.body.dataset.shell") == "overlay"
        assert page.evaluate("document.body.dataset.view") == "active-match"

        # Compact subset present: coach CALL pane + BUILD pane.
        call = page.locator("#view-active-match .am-pane-call")
        build = page.locator("#view-active-match .am-pane-build")
        assert call.is_visible(), ".am-pane-call not visible in overlay"
        assert build.is_visible(), ".am-pane-build not visible in overlay"
        # The fixture's coach payload actually rendered into the CALL pane.
        assert page.locator("#am-call-body div").count() > 0, "CALL pane empty"

        # Callouts/lead mounts ride along inside the subset (they paint
        # whenever the deterministic generators ship data).
        assert page.locator("#rn-lead").count() == 1, "#rn-lead mount missing"
        assert page.locator("#rn-callouts").count() == 1, "#rn-callouts mount missing"

        # Non-subset active-match panes are hidden (GPU-light overlay).
        assert _display(page, ".am-pane-map") == "none", "map pane should hide"
        assert _display(page, ".am-pane-cd") == "none", "cd pane should hide"

        # Header / footer / every other view is display:none.
        for sel in _HIDDEN_SELECTORS:
            assert _display(page, sel) == "none", f"{sel} should be display:none"

        # Transparent page background (Electron window is transparent).
        bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
        assert bg in ("rgba(0, 0, 0, 0)", "transparent"), (
            f"body background not transparent: {bg}"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "overlay_sr.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [overlay]: {errors[:3]}"


def test_overlay_right_dock_geometry(mock_server, pw_browser):
    """The visible column is ~460px wide and docked to the right edge of
    the 1920 viewport (the rest of the window stays transparent for the
    click-through game area)."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        box = page.locator("#view-active-match").bounding_box()
        assert box is not None, "#view-active-match has no box"
        assert 420 <= box["width"] <= 480, f"dock width {box['width']} not ~460"
        assert box["x"] + box["width"] >= 1430, (
            f"dock not right-anchored (right edge {box['x'] + box['width']})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [geometry]: {errors[:3]}"


def test_overlay_callouts_lead_whitelist(mock_server, pw_browser):
    """Inside #right-now only the lead/callouts/choices mounts may show:
    when a callout lands (un-hidden + populated) it displays, while the
    full-grid coach chrome (#rn-action etc.) stays display:none."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.evaluate(
            "() => {"
            "  const co = document.getElementById('rn-callouts');"
            "  co.hidden = false;"
            "  co.innerHTML = '<div class=\"rc-co-row\">"
            "<span class=\"rc-co-line\">Drake spawns - rotate bot</span>"
            "<span class=\"rc-co-eta\">0:45</span></div>';"
            "}"
        )
        assert _display(page, "#rn-callouts") != "none", (
            "#rn-callouts should display when populated in overlay"
        )
        assert page.locator("#rn-callouts .rc-co-row").is_visible()
        # The 1920-grid coach chrome stays hidden in the overlay shell.
        assert _display(page, "#rn-action") == "none", "#rn-action should hide"
        assert _display(page, "#right-now .rn-screenread") == "none", (
            "screen-read button should hide in overlay"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [callouts whitelist]: {errors[:3]}"


def test_overlay_change_pulse_hook(mock_server, pw_browser):
    """overlay_pulse.js: a content change inside an overlay panel adds the
    .ov-pulse edge-glow class to its container for ~1.2s, then drops it."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        # Let the initial mock-render pulse window + throttle expire.
        page.wait_for_timeout(1700)
        page.evaluate(
            "() => {"
            "  const d = document.createElement('div');"
            "  d.textContent = 'ROTATE MID - spike online';"
            "  document.getElementById('am-call-body').appendChild(d);"
            "}"
        )
        page.wait_for_function(
            "document.querySelector('.am-pane-call').classList.contains('ov-pulse')",
            timeout=3_000,
        )
        # One-shot: the class is dropped again after ~1.2s.
        page.wait_for_function(
            "!document.querySelector('.am-pane-call').classList.contains('ov-pulse')",
            timeout=4_000,
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [pulse]: {errors[:3]}"


def test_overlay_pulse_suppressed_when_toggle_off(mock_server, pw_browser):
    """OVL1: pulseNotify=false (operator muted the change-pulse via the overlay
    settings toggle) suppresses the .ov-pulse glow even on a real content
    change. The gate reads the shared localStorage mirror at fire time."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    # Mute the pulse BEFORE any page script runs (init scripts run pre-load on
    # every navigation), mirroring the operator having toggled it off earlier.
    page.add_init_script(
        "try { localStorage.setItem('rc_overlay_settings',"
        " JSON.stringify({pulseNotify:false, activeRevertSec:20})); } catch (e) {}"
    )
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=sr&overlay=1",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#am-sub') && "
            "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
            timeout=10_000,
        )
        # Let the initial mock-render pulse window + throttle expire.
        page.wait_for_timeout(1700)
        page.evaluate(
            "() => {"
            "  const d = document.createElement('div');"
            "  d.textContent = 'ROTATE MID - spike online';"
            "  document.getElementById('am-call-body').appendChild(d);"
            "}"
        )
        # Give the observer + any timer a beat, then assert the glow never landed.
        page.wait_for_timeout(700)
        assert not page.evaluate(
            "document.querySelector('.am-pane-call').classList.contains('ov-pulse')"
        ), "pulse must be suppressed when pulseNotify=false"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [pulse off]: {errors[:3]}"


def test_no_overlay_param_keeps_normal_shell(mock_server, pw_browser):
    """Control: the C2 drive path without overlay=1 must not pick up the
    overlay shell - header stays visible, no data-shell attribute."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=sr#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#am-sub') && "
            "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
            timeout=10_000,
        )
        assert page.evaluate("document.body.dataset.shell || ''") == ""
        assert _display(page, "header") != "none", "header must stay visible"
        assert _display(page, ".am-pane-map") != "none", "map pane must stay"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [control]: {errors[:3]}"


def _open_overlay_set(pw_browser, mock_server, panelset):
    return _open_overlay(
        pw_browser, mock_server,
        query=f"?ui_mock=1&mode=sr&overlay=1&panelset={panelset}",
    )


def test_panelset_coach_hides_build(mock_server, pw_browser):
    """panelset=coach: CALL pane + right-now mounts only - BUILD pane off."""
    ctx, page, errors = _open_overlay_set(pw_browser, mock_server, "coach")
    try:
        assert page.evaluate("document.body.dataset.panelset") == "coach"
        assert page.locator("#view-active-match .am-pane-call").is_visible()
        assert _display(page, ".am-pane-build") == "none", "build pane should hide"
        assert _display(page, "main") != "none", "mount column must stay"
        assert page.locator("#rn-lead").count() == 1
        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "overlay_sr_coach.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [panelset coach]: {errors[:3]}"


def test_panelset_build_shows_build_only(mock_server, pw_browser):
    """panelset=build: BUILD pane only - CALL pane + the right-now mount
    column are off."""
    ctx, page, errors = _open_overlay_set(pw_browser, mock_server, "build")
    try:
        assert page.evaluate("document.body.dataset.panelset") == "build"
        assert page.locator("#view-active-match .am-pane-build").is_visible()
        assert _display(page, ".am-pane-call") == "none", "call pane should hide"
        assert _display(page, "main") == "none", "mount column should hide"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "overlay_sr_build.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [panelset build]: {errors[:3]}"


def test_panelset_threat_shows_cds_lead_callouts(mock_server, pw_browser):
    """panelset=threat: the CDS cooldown ledger + lead/callouts timing
    surfaces - CALL/BUILD panes and the A+B choice chips are off."""
    ctx, page, errors = _open_overlay_set(pw_browser, mock_server, "threat")
    try:
        assert page.evaluate("document.body.dataset.panelset") == "threat"
        assert _display(page, ".am-pane-cd") != "none", "cd pane must show"
        assert _display(page, ".am-pane-call") == "none", "call pane should hide"
        assert _display(page, ".am-pane-build") == "none", "build pane should hide"
        # Choices are a coach-set surface: even populated they stay off here.
        page.evaluate(
            "() => {"
            "  const ch = document.getElementById('rn-choices');"
            "  ch.hidden = false;"
            "  ch.innerHTML = '<button class=\"rc-chip\">A</button>';"
            "}"
        )
        assert _display(page, "#rn-choices") == "none", "choices should hide"
        # Lead/callouts still displayable (timing surfaces).
        page.evaluate(
            "() => {"
            "  const co = document.getElementById('rn-callouts');"
            "  co.hidden = false;"
            "  co.innerHTML = '<div class=\"rc-co-row\">"
            "<span class=\"rc-co-line\">Drake 0:45</span></div>';"
            "}"
        )
        assert _display(page, "#rn-callouts") != "none", "callouts must show"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "overlay_sr_threat.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [panelset threat]: {errors[:3]}"


def test_panelset_unknown_or_absent_keeps_full_subset(mock_server, pw_browser):
    """Defensive: an unknown panelset never stamps the attribute, so the
    S1 full compact subset (CALL + BUILD + mounts) renders unchanged; the
    plain ?overlay=1 URL stays backward compatible."""
    ctx, page, errors = _open_overlay_set(pw_browser, mock_server, "garbage")
    try:
        assert page.evaluate("document.body.dataset.panelset || ''") == ""
        assert page.locator("#view-active-match .am-pane-call").is_visible()
        assert page.locator("#view-active-match .am-pane-build").is_visible()
        assert _display(page, "main") != "none"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [panelset unknown]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in the
    overlay-route files this slice adds."""
    targets = [
        Path(__file__),
        ROOT / "web" / "css" / "overlay.css",
        ROOT / "web" / "js" / "overlay_pulse.js",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
