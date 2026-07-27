"""OQ16 (OQ3 variant A): rendered-Chromium proof of the objective gauge
cluster on the overlay route.

Drive path mirrors test_overlay_view.test_overlay_minimap_rect_threads_
through_live_state: a LIVE (non-ui_mock) SSE envelope with mode_key=sr +
liveclient {game_time_s, objective_events} + the top-level
summoner_cooldowns ledger - the exact /api/state siblings the live
dispatch site threads (main.js live branch). This proves the live wiring,
not just the mock path (the ui_mock fixture's liveclient carries no
game_time_s, so the widget stays honestly hidden there).

Covered:
  1. in-game SR: 3 dials render with the exact schedule ETAs + doctrine
     hues + the ovx-widget field registration.
  2. idle (empty envelope): the widget hides entirely - no placeholder.
  3. non-SR (aram): hidden - ARAM has no epic objectives
     (core/event_callouts.py: neutral objectives are SR-only).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRATCH = ROOT / "_scratch"

# Expected doctrine hues (operator OQ3/OQ16 pick, docs/OVERLAY_DOCTRINE.md
# sec 5): DRAKE #E8A33D, BARON #C8AA6E, ELDER #E84057.
_HUES = {
    "drake": "rgb(232, 163, 61)",
    "baron": "rgb(200, 170, 110)",
    "elder": "rgb(232, 64, 87)",
}

# A live SR envelope at game clock 6:00 (360s):
#   - drake: elemental (Fire) taken at 5:00 -> respawn 300+300=600 -> 4:00.
#   - baron: no kill yet -> static first spawn 1200 -> 14:00.
#   - elder: nominal late marker 2100 -> 29:00.
_SR_STATE = {
    "mode_key": "sr",
    "coach": {"action": "Push mid", "immediate": "Group up", "kda": "1/0/0"},
    "liveclient": {
        "level": 6,
        "game_time_s": 360,
        "objective_events": [
            {"name": "dragon", "killer_team": "ally", "down_at_s": 300,
             "dragon_type": "Fire"},
        ],
    },
    "summoner_cooldowns": [
        {
            "puuid": None, "summoner_name": "enemy1", "champion_id": None,
            "side": "red",
            "summs": {
                "d_id": 4, "d_name": "Flash", "d_used_at_s": 100,
                "d_ready_at_s": 400, "d_cd_remaining_s": 90,
                "f_id": 14, "f_name": "Ignite", "f_used_at_s": None,
                "f_ready_at_s": 0, "f_cd_remaining_s": 0,
                "summoner_haste": 0,
            },
            "ult": {"id": None, "used_at_s": None, "ready_at_s": 0,
                    "cd_remaining_s": 0, "ability_haste": 0},
        },
    ],
}


def _open_live(pw_browser, mock_server, data, query="?overlay=1&mode=sr"):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = data
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/" + query,
              wait_until="domcontentloaded", timeout=15_000)
    return ctx, page, errors


def _css(page, selector, prop):
    return page.eval_on_selector(
        selector, "(el, p) => getComputedStyle(el).getPropertyValue(p)", prop
    )


def test_gauges_render_live_sr_state(mock_server, pw_browser):
    """A live SR envelope paints all 3 dials with the exact schedule ETAs,
    per-dial doctrine hues on the ring arc, and the movable ovx-widget
    field registration (w-objgauges)."""
    ctx, page, errors = _open_live(pw_browser, mock_server, dict(_SR_STATE))
    try:
        page.wait_for_function(
            "() => { const m = document.getElementById('am-obj-gauges');"
            " return m && !m.hidden &&"
            " m.querySelectorAll('.og-dial').length === 3; }",
            timeout=10_000,
        )
        # Exact ETA centers (canonical schedule + game_time arithmetic).
        for key, eta in (("drake", "4:00"), ("baron", "14:00"),
                         ("elder", "29:00")):
            txt = page.eval_on_selector(
                f'#am-obj-gauges .og-dial[data-obj="{key}"] .og-eta',
                "el => el.textContent")
            assert txt == eta, f"{key} ETA {txt!r} != {eta!r}"

        # Ring arc carries the per-objective doctrine hue.
        for key, hue in _HUES.items():
            stroke = _css(
                page, f'#am-obj-gauges .og-dial[data-obj="{key}"] .og-arc',
                "stroke")
            assert stroke == hue, f"{key} arc stroke {stroke!r} != {hue!r}"

        # ovx-widget field registration at its ambient default.
        assert page.eval_on_selector(
            "#am-obj-gauges", "e => e.classList.contains('ovx-widget')"
        ), "#am-obj-gauges is not an .ovx-widget"
        assert page.eval_on_selector(
            "#am-obj-gauges", "e => e.dataset.ovxId") == "w-objgauges"
        assert _css(page, "#am-obj-gauges", "position") == "fixed"
        # 1632 not the old 1690: at --ovx-w 288 that put the right edge at 1978,
        # i.e. 58px off a 1920 screen (2026-07-27 default-collision sweep).
        assert _css(page, "#am-obj-gauges", "left") == "1632px"
        parent = page.eval_on_selector(
            "#am-obj-gauges", "e => e.parentElement.className")
        assert "am-grid" in parent, f"mount not an am-grid child: {parent!r}"

        # Labels stay readable-size (>= the 13px overlay chip token) and the
        # ETA clears the 16px --fs-xs floor.
        label_fs = page.eval_on_selector(
            '#am-obj-gauges .og-dial[data-obj="drake"] .og-label',
            "el => parseFloat(getComputedStyle(el).fontSize)")
        assert label_fs >= 13, f"label font {label_fs} below 13px"
        eta_fs = page.eval_on_selector(
            '#am-obj-gauges .og-dial[data-obj="drake"] .og-eta',
            "el => parseFloat(getComputedStyle(el).fontSize)")
        assert eta_fs >= 16, f"eta font {eta_fs} below the 16px floor"

        SCRATCH.mkdir(exist_ok=True)
        page.screenshot(path=str(SCRATCH / "oq16_objective_gauges_sr.png"))
        page.locator("#am-obj-gauges").screenshot(
            path=str(SCRATCH / "oq16_objective_gauges_widget.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [gauges live sr]: {errors[:3]}"


def test_gauges_double_alert_cadence_paints(mock_server, pw_browser):
    """BACKLOG "Overlay HUD micro-lifts" (a): a counting-down dial escalates
    twice - data-og-alert "soon" at 90s, "imminent" at 10s. Proven on the
    BARON dial's static first spawn (1200s), and the escalation must NOT move
    any geometry (no-reflow law)."""
    def _baron_at(clock_s):
        d = {k: v for k, v in _SR_STATE.items()}
        d["liveclient"] = {"level": 6, "game_time_s": clock_s,
                           "objective_events": []}
        return d

    def _alert_and_box(clock_s):
        ctx, page, errors = _open_live(pw_browser, mock_server,
                                       _baron_at(clock_s))
        try:
            page.wait_for_function(
                "() => { const m = document.getElementById('am-obj-gauges');"
                " return m && !m.hidden &&"
                " m.querySelectorAll('.og-dial').length === 3; }",
                timeout=10_000,
            )
            alert = page.eval_on_selector(
                '#am-obj-gauges .og-dial[data-obj="baron"]',
                "el => el.dataset.ogAlert")
            box = page.eval_on_selector(
                "#am-obj-gauges .og-grid",
                "el => { const r = el.getBoundingClientRect();"
                " return [Math.round(r.width), Math.round(r.height)]; }")
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [gauges alert @{clock_s}]: {errors[:3]}"
        return alert, box

    quiet, box_quiet = _alert_and_box(600)     # eta 10:00 -> no alert
    soon, box_soon = _alert_and_box(1150)      # eta 0:50  -> soon
    imminent, box_imm = _alert_and_box(1195)   # eta 0:05  -> imminent
    assert quiet == "", f"far-out dial must stay quiet, got {quiet!r}"
    assert soon == "soon", f"eta 50s must be 'soon', got {soon!r}"
    assert imminent == "imminent", f"eta 5s must be 'imminent', got {imminent!r}"
    # NO REFLOW: escalation is colour + opacity only.
    assert box_quiet == box_soon == box_imm, (
        f"alert tiers moved the cluster: {box_quiet} / {box_soon} / {box_imm}")


def test_gauges_hidden_when_idle(mock_server, pw_browser):
    """HONEST NO-DATA: an empty envelope (no live game) keeps the widget
    hidden entirely - display none, no placeholder ghosts."""
    ctx, page, errors = _open_live(pw_browser, mock_server, {})
    try:
        page.wait_for_timeout(1500)
        assert page.eval_on_selector(
            "#am-obj-gauges", "el => el.hidden"), "widget must stay hidden idle"
        assert _css(page, "#am-obj-gauges", "display") == "none"
        # No RENDER content while idle (the lone permitted child is the
        # .ovx-handle drag chrome overlay_layout.js injects into every
        # registered field widget - not a data placeholder).
        assert page.eval_on_selector(
            "#am-obj-gauges", "el => el.querySelector('.og-grid') === null"), (
            "no placeholder dials may render while idle")
        assert page.eval_on_selector(
            "#am-obj-gauges",
            "el => [...el.children].every("
            "c => c.classList.contains('ovx-handle'))"), (
            "only the field drag handle may exist while idle")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [gauges idle]: {errors[:3]}"


def test_gauges_hidden_in_non_sr_mode(mock_server, pw_browser):
    """SR-only gate: ARAM has no epic objectives (core/event_callouts.py) -
    a live aram envelope with a game clock must NOT paint the widget."""
    data = {
        "mode_key": "aram",
        "coach": {"action": "Poke", "immediate": "Hold", "kda": "0/0/0"},
        "liveclient": {"level": 4, "game_time_s": 300,
                       "objective_events": []},
        "summoner_cooldowns": None,
    }
    ctx, page, errors = _open_live(pw_browser, mock_server, data,
                                   query="?overlay=1&mode=aram")
    try:
        # Let the SSE envelope land + render (the coach pane proves it).
        page.wait_for_timeout(1500)
        assert page.eval_on_selector(
            "#am-obj-gauges", "el => el.hidden"), (
            "widget must stay hidden outside SR")
        assert _css(page, "#am-obj-gauges", "display") == "none"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [gauges non-sr]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text in this test file."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
