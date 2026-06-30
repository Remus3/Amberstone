"""
tests/snapshot_panels/test_overlay_view.py
Electron overlay route (RC Overlay Doctrine, docs/OVERLAY_DOCTRINE.md).

The in-game overlay window loads RC_ORIGIN/?overlay=1. main.js stamps
body[data-shell="overlay"] at module top (before the first render) and the
view router pins the active-match view unconditionally - hash / manual /
auto derivation are bypassed. web/css/overlay.css + web/js/lib/overlay_layout.js
then compose a FULLSCREEN transparent click-through page as a FIELD of
independently absolutely-positioned widgets (the .ovx-widget accents), NOT the
retired 460px right-dock. Each cue mount (the coach CALL pane, the A/B choice
chips, the lead pill, the objective/spike callouts, the enemy CD ledger, the
build re-rank, the fight-model knobs) is lifted to position:fixed at a saved-or-
default (x,y); the default is the eye-line anchor map (OVERLAY_DOCTRINE section 4:
call upper-center 760,140; lead under the score bar 786,44; callouts at the
minimap; spike bottom-left). ALL panels are accessible (the coach/build/threat
panel-set auto-hide was retired 2026-06-28); per-widget .ovx-hidden is the only
visibility gate. Header / nav / footer / every other view is display:none over a
transparent background.

Drive path mirrors test_active_match_view.py (C2):
/?ui_mock=1&mode=sr&overlay=1. The forced applyView("active-match") fires
_amMockLoad, which fetches /data/ui_mock/active_match_sr.json and renders
the CALL pane with phase=InProgress - we wait on that #am-sub stamp.

Also covered: the panel-set deltas (coach core persists; build adds w-build,
threat adds w-threat + drops choices), the ovscale body-zoom of the field, the
.ov-pulse change-glow hook (web/js/overlay_pulse.js), and the no-overlay-param
control (normal shell untouched). 2026-06-21: rewritten off the retired 460px
dock model to the widget field (the @_DOCK_RETIRED skip marker is gone).
"""
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


def _css(page, selector, prop):
    """Resolved computed value of a (dash-cased) CSS property on the first match."""
    return page.eval_on_selector(
        selector, "(el, p) => getComputedStyle(el).getPropertyValue(p)", prop
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


def test_overlay_shell_is_widget_field(mock_server, pw_browser):
    """?overlay=1: shell flag + forced active-match view, then the cue mounts are
    lifted to absolutely-positioned .ovx-widget accents (the widget FIELD, not a
    dock). All widgets paint at their eye-line anchor default (panel-set auto-hide
    retired 2026-06-28 - every panel is accessible); header / footer / every other
    view is display:none over a transparent page (doctrine 2+4)."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        # Shell flag + forced view.
        assert page.evaluate("document.body.dataset.shell") == "overlay"
        assert page.evaluate("document.body.dataset.view") == "active-match"

        # The coach-set cue mounts are .ovx-widget + position:fixed (the field).
        for sel, wid in (
            ("#rn-lead", "w-lead"),
            ("#view-active-match .am-pane-call", "w-call"),
            ("#rn-callouts", "w-callouts"),
        ):
            assert page.eval_on_selector(
                sel, "e => e.classList.contains('ovx-widget')"
            ), f"{sel} is not an .ovx-widget"
            assert page.eval_on_selector(sel, "e => e.dataset.ovxId") == wid, (
                f"{sel} missing data-ovx-id={wid}"
            )
            assert _css(page, sel, "position") == "fixed", f"{sel} not position:fixed"

        # Left-gutter default (operator 2026-06-27 nudged w-call off-center: 760,140
        # -> 180,130 to clear the play column), and the PRIMARY carries its tier marker.
        assert _css(page, "#view-active-match .am-pane-call", "left") == "180px"
        assert page.eval_on_selector(
            "#view-active-match .am-pane-call", "e => e.dataset.ovxTier"
        ) == "primary"
        # The fixture's coach payload actually rendered into the CALL pane.
        assert page.locator("#am-call-body div").count() > 0, "CALL pane empty"

        # All-panels-accessible doctrine (operator 2026-06-28): the panel-set
        # auto-hide is retired, so the formerly reveal-only build / CDS ledger /
        # fight-model panes all SHOW by default (per-widget .ovx-hidden is now the
        # only gate). See test_all_panels_visible_by_default for the focused check.
        for sel in (
            "#view-active-match .am-pane-build",
            "#view-active-match .am-pane-cd",
            "#am-pane-ovds",
        ):
            assert _display(page, sel) != "none", (
                f"{sel} must be visible by default (all panels accessible)"
            )
        # The map pane never paints on the HUD.
        assert _display(page, ".am-pane-map") == "none", "map pane should hide"

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
    assert not errors, f"JS errors [overlay field]: {errors[:3]}"


def test_overlay_settings_strip_reveals_in_build_set(mock_server, pw_browser):
    """Overlay-only doctrine: the #ovset settings strip rides the w-ovds
    fight-model widget, which is REVEAL-ONLY - it shows in the build set, not the
    default coach HUD. When revealed it carries the overlay-native controls: the
    panel-set selector (Coach/Build/Threat, twin of Alt+Shift+C), Interact-now
    (twin of Alt+Shift+A), the change-pulse toggle, and the auto-passive seconds
    field. Each clears the >=42px hit-target floor with ASCII labels.

    keep-vs-RETIRE decision (2026-06-21): the companion-coexistence controls
    (Keep-dashboard / Pin-on-top / Separate-windows / Re-arrange / Show-dashboard)
    are NO LONGER asserted. The Chrome dashboard is retired as a user surface
    (docs/OVERLAY_DOCTRINE.md), so those manage a deprecated surface; they still
    render (wired in rc-shell) but are not pinned as test contract. The three
    dock-era #ovset tests are consolidated here."""
    ctx, page, errors = _open_overlay_set(pw_browser, mock_server, "build")
    try:
        # The strip mounts via renderOverlayDsControls -> _ensureScaffold and is
        # revealed because its host w-ovds widget shows in the build set.
        page.wait_for_selector("#ovset #ovset-panelset", timeout=10_000)
        assert _display(page, "#am-pane-ovds") != "none", (
            "the settings-strip host (w-ovds) must reveal in the build set"
        )

        # STRUCTURE: the overlay-native controls are present.
        for sel in ("#ovset-panelset", "#ovset-interact", "#ovset-pulse", "#ovset-revert"):
            assert page.locator(sel).count() == 1, f"{sel} missing from #ovset"
        for ps in ("coach", "build", "threat"):
            assert page.locator(f'#ovset-panelset [data-panelset="{ps}"]').count() == 1, (
                f"panel-set segment {ps} missing"
            )

        # ASCII labels (no smart quotes / dashes).
        for sel, want in (
            ('#ovset-panelset [data-panelset="coach"]', "Coach"),
            ("#ovset-interact", "Interact now"),
        ):
            txt = page.eval_on_selector(sel, "el => el.textContent")
            assert txt == want, f"unexpected label {txt!r} for {sel}"
            assert txt.isascii(), f"non-ASCII label {txt!r}"

        # HIT-TARGETS: a segment + the interact button clear the 42px floor.
        hseg = page.eval_on_selector(
            '#ovset-panelset [data-panelset="coach"]',
            "el => el.getBoundingClientRect().height",
        )
        assert hseg >= 42, f"panel-set segment height {hseg} below 42px floor"
        hact = page.eval_on_selector(
            "#ovset-interact", "el => el.getBoundingClientRect().height"
        )
        assert hact >= 42, f"Interact-now height {hact} below 42px floor"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [ovset reveal]: {errors[:3]}"


def test_overlay_panelset_selector_reflects_active_set(mock_server, pw_browser):
    """RC2 4.4: loaded at ?panelset=build the selector lights the Build segment
    (aria-pressed=true + is-active) and only that one - it reflects the live
    overlay panel set without a shell round-trip."""
    ctx, page, errors = _open_overlay_set(pw_browser, mock_server, "build")
    try:
        page.wait_for_selector("#ovset #ovset-panelset", timeout=10_000)
        assert page.eval_on_selector(
            '#ovset-panelset [data-panelset="build"]', "el => el.getAttribute('aria-pressed')"
        ) == "true", "Build segment must be aria-pressed when panelset=build"
        assert page.eval_on_selector(
            '#ovset-panelset [data-panelset="build"]',
            "el => el.classList.contains('is-active')",
        ) is True, "Build segment must carry .is-active"
        # exactly one lit segment.
        assert page.locator('#ovset-panelset [aria-pressed="true"]').count() == 1
        assert page.eval_on_selector(
            '#ovset-panelset [data-panelset="coach"]', "el => el.getAttribute('aria-pressed')"
        ) == "false", "Coach segment must not be active when panelset=build"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [4.4 reflect]: {errors[:3]}"


def test_overlay_widget_field_eye_line_positions(mock_server, pw_browser):
    """The widgets are an absolutely-positioned FIELD (position:fixed) placed at
    the EYE-LINE ANCHORS, NOT a ~460px right-anchored dock. Each coach-set widget
    sits at its doctrine section-4 default (lead under the score bar 786,44; call
    upper-center 760,140; callouts at the minimap 1486,780) and renders as a narrow
    accent, so the field hugs the eye, not a fat corner dock (doctrine section 4)."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        # Field facts hold for every mount; computed style resolves even when a
        # data-driven mount is still [hidden] in the empty-SSE fixture. Each mount
        # sits at its eye-line default `left` (doctrine section-4 (x,y) table).
        for sel, left in (
            ("#rn-lead", "786px"),
            ("#view-active-match .am-pane-call", "180px"),
            ("#rn-callouts", "1486px"),
        ):
            assert _css(page, sel, "position") == "fixed", f"{sel} not position:fixed"
            assert _css(page, sel, "left") == left, (
                f"{sel} not at its eye-line default ({left})"
            )
        # No ~460px dock any more: the visible primary is a narrow accent at its
        # left-gutter anchor, not a fat right-edge column.
        call = page.locator("#view-active-match .am-pane-call").bounding_box()
        assert call is not None, "call widget has no box"
        assert 170 <= call["x"] <= 190, f"call not at its left-gutter anchor (x={call['x']})"
        assert call["width"] <= 280, (
            f"widget width {call['width']} should be a narrow accent, not a ~460 dock"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [field geometry]: {errors[:3]}"


def test_overlay_call_value_tiering(mock_server, pw_browser):
    """The CALL value tiers are keyed on data-call-line (NOT a fragile nth-child)
    and override _line()'s inline span styles via !important: the OBJECTIVE value
    clamps to 2 lines (rule 1 glance budget), and the tier COLORS apply - cyan
    RIGHT NOW (imminent cue), white ACTION (the verb), faint OBJECTIVE (the macro
    footer). The data-ink eyebrow labels drop."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        obj = '#am-call-body > div[data-call-line="objective"] > span:last-child'
        assert page.locator(obj).count() == 1, "no OBJECTIVE line rendered"
        # 2026-06-29: bumped 2 -> 3 lines (operator: objective truncated mid-sentence).
        assert _css(page, obj, "-webkit-line-clamp") == "3", "OBJECTIVE not clamped to 3 lines"
        # Tier colors apply over the inline color:var(--text) (needs !important).
        rn = _css(page, '#am-call-body > div[data-call-line="right-now"] > span:last-child', "color")
        assert "10, 200, 185" in rn, f"RIGHT NOW value not cyan (got {rn!r})"
        assert "0.55" in _css(page, obj, "color"), "OBJECTIVE value not faint"
        # Eyebrow labels drop for data-ink (rule 8) - beats the inline display:block.
        assert _display(
            page, '#am-call-body > div[data-call-line="objective"] > span:first-child'
        ) == "none", "the OBJECTIVE eyebrow label must drop"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [call tiering]: {errors[:3]}"


def test_overlay_call_action_band_channel(mock_server, pw_browser):
    """RC Overlay Doctrine section 5/6: the PRIMARY w-call ACTION line carries the
    band channel the spec->doctrine S0 dock-retirement dropped - a data-call-band
    keyed off classifyAction(verb), a band-colored glyph prefix, and a color-bar
    left border (urgent=red / fight=gold / good=green). The verb TEXT stays white
    (doctrine line 164 - the verb is not recolored; the glyph + bar carry the
    category so urgent vs good no longer read identically white). This is the
    preattentive signal the combat-shed (section 6, overlay.css:570) leans on."""
    BAND_RGB = {
        "urgent": "232, 64, 87",   # --ovx-red, the reserved emergency pop-out
        "fight": "200, 170, 110",  # --ovx-gold, the single caution hue
        "good": "55, 208, 138",    # --ovx-good
    }
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        row = '#am-call-body > div[data-call-line="action"]'
        assert page.locator(row).count() == 1, "no ACTION line rendered"

        # JS wiring: the row is stamped with a band, and it equals the SHIPPED
        # classifyAction over the rendered verb (proves the render actually called
        # classifyAction, not a hardcoded band - guards the fixture-shaped-to-bug
        # failure mode: the assertion tracks whatever band the real logic derives).
        band = page.eval_on_selector(row, "e => e.dataset.callBand")
        assert band in BAND_RGB, f"ACTION row missing a valid data-call-band: {band!r}"
        verb = page.eval_on_selector(
            row, "e => e.lastElementChild.lastChild.textContent.trim()"
        )
        expected = page.evaluate(
            "async (t) => (await import('/js/lib/helpers.js')).classifyAction(t)", verb
        )
        assert band == expected, (
            f"data-call-band {band!r} != classifyAction({verb!r})={expected!r}"
        )

        # The band-colored glyph prefix exists (a functional U+26A0/2713/25BA action
        # glyph emitted from JS so overlay.css stays 7-bit ASCII) and is band-colored.
        assert page.locator(f"{row} .am-call-glyph").count() == 1, "no band glyph"
        glyph_color = _css(page, f"{row} .am-call-glyph", "color")
        assert BAND_RGB[band] in glyph_color, (
            f"glyph color {glyph_color!r} is not the {band} token {BAND_RGB[band]}"
        )

        # The color BAR (left border) tracks the band token.
        bar = _css(page, row, "border-left-color")
        assert BAND_RGB[band] in bar, (
            f"action color-bar {bar!r} is not the {band} token {BAND_RGB[band]}"
        )

        # Doctrine line 164: the verb itself stays white (--ovx-text) - the band
        # is carried by the glyph + bar, never by recoloring the play verb.
        verb_color = _css(page, f"{row} > span:last-child", "color")
        assert "255, 255, 255" in verb_color, (
            f"ACTION verb must stay white (--ovx-text), got {verb_color!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [action band channel]: {errors[:3]}"


def test_overlay_combat_mode_declutter(mock_server, pw_browser):
    """Doctrine section 6: body[data-fight="1"] (combat_mode flags a high-stakes
    moment) sheds load - the ambient lead pill hides and the CALL drops its macro
    OBJECTIVE footer, but the RIGHT NOW cue + the ACTION verb + the primary widget
    persist (text -> preattentive). The lead-pill hide is the #rn-lead id-mount, so
    it must out-rank the section-4a flex rule (the same specificity lesson as the
    panel-set choices hide)."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.evaluate(
            "() => {"
            "  const ld = document.getElementById('rn-lead');"
            "  ld.hidden = false; ld.innerHTML = '<span>+1.2k gold</span>';"
            "  document.body.dataset.fight = '1';"
            "}"
        )
        assert _display(page, "#rn-lead") == "none", "the lead pill must shed in combat"
        assert _display(page, "#view-active-match .am-pane-call") != "none", (
            "the primary call must persist in combat"
        )
        # Keyed on data-call-line (rows are conditional, not fixed nth-child).
        assert _display(page, '#am-call-body > div[data-call-line="right-now"]') != "none", (
            "RIGHT NOW must stay in combat"
        )
        assert _display(page, '#am-call-body > div[data-call-line="action"]') != "none", (
            "ACTION must stay in combat"
        )
        assert _display(page, '#am-call-body > div[data-call-line="objective"]') == "none", (
            "the macro OBJECTIVE footer must shed in combat"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [combat declutter]: {errors[:3]}"


def test_overlay_new_cue_widgets_are_movable_field_mounts(mock_server, pw_browser):
    """RC Overlay Doctrine w-trinket + w-spike: the trinket-ready + spike-crossed
    cues are registered as movable, position-fixed .ovx-widget field mounts at
    their eye-line default (w-trinket by the avatar 920,540; w-spike bottom-left by
    the champion stats 360,840). They sit as direct am-grid children (NOT inside a
    transformed .ovx-widget pane) so position:fixed is viewport-relative, not
    trapped + clipped by a pane's transform containing block."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        for sel, wid, left in (
            ("#am-ward-cue", "w-trinket", "340px"),
            ("#am-spike-cue", "w-spike", "360px"),
        ):
            assert page.eval_on_selector(
                sel, "e => e.classList.contains('ovx-widget')"
            ), f"{sel} is not an .ovx-widget"
            assert page.eval_on_selector(sel, "e => e.dataset.ovxId") == wid
            assert _css(page, sel, "position") == "fixed", f"{sel} not position:fixed"
            assert _css(page, sel, "left") == left, (
                f"{sel} not at its eye-line default ({left})"
            )
            parent = page.eval_on_selector(sel, "e => e.parentElement.className")
            assert "am-grid" in parent, (
                f"{sel} must mount in am-grid, not a transformed pane (got {parent!r})"
            )
        # data-gated (hidden until actionable in the empty-SSE mock): force-show
        # the spike cue and confirm it lands at its viewport-fixed default x ~= 360
        # (a transform-trapped fixed child would be offset by the pane's position).
        page.evaluate(
            "() => { const s = document.getElementById('am-spike-cue');"
            "  s.hidden = false;"
            "  s.innerHTML = '<span class=\"spike-chip\">ULT ONLINE</span>'; }"
        )
        box = page.locator("#am-spike-cue").bounding_box()
        assert box is not None and abs(box["x"] - 360) < 6, (
            f"spike cue not viewport-fixed at x~360 (trapped?): {box and box['x']}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [new cue widgets]: {errors[:3]}"


def test_overlay_minimap_rect_is_clickthrough_outline_widget(mock_server, pw_browser):
    """RC Overlay Doctrine w-mmrect (ZOI foundation): the settings-driven minimap
    outline is a position-fixed .ovx-widget mounted as a direct am-grid child,
    rendered at the game.cfg-derived rect from /api/state.minimap_rect (the mock
    fixture ships x=1600,y=760,w=312,h=312). It is OUTLINE-ONLY (transparent
    backing, gold hairline border, no hex-notch bracket) and CLICK-THROUGH
    (pointer-events:none) so League minimap clicks pass through; it is
    settings-pinned (no drag handle)."""
    sel = "#am-mmrect"
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        assert page.eval_on_selector(
            sel, "e => e.classList.contains('ovx-widget')"
        ), f"{sel} is not an .ovx-widget"
        assert page.eval_on_selector(sel, "e => e.dataset.ovxId") == "w-mmrect"
        assert page.eval_on_selector(sel, "e => !e.hidden"), f"{sel} should be shown"
        assert _css(page, sel, "position") == "fixed", f"{sel} not position:fixed"
        # game.cfg-derived rect placed by WINDOW FRACTION + the operator calibration
        # nudge (2026-06-29: x/1920*innerWidth + 6px right, y/1080*innerHeight + 2px
        # down; at the 1920x1080 test viewport with bodyZoom=1 -> 1600+6, 760+2). The
        # box is now ovscale-immune (zoom=1/bodyZoom) - see minimap_rect._placement.
        assert _css(page, sel, "left") == "1606px", f"{sel} not at settings x"
        assert _css(page, sel, "top") == "762px", f"{sel} not at settings y"
        assert _css(page, sel, "width") == "312px", f"{sel} wrong width"
        assert _css(page, sel, "height") == "312px", f"{sel} wrong height"
        # click-through (no grab zone over the minimap)
        assert _css(page, sel, "pointer-events") == "none", f"{sel} not click-through"
        # outline-only: transparent backing + a gold hairline (--ovx-gold)
        assert _css(page, sel, "background-color") == "rgba(0, 0, 0, 0)", (
            f"{sel} backing not transparent"
        )
        assert "200, 170, 110" in _css(page, sel, "border-top-color"), (
            f"{sel} border is not the --ovx-gold hairline"
        )
        # no drag handle (settings-pinned, click-through-safe)
        assert page.eval_on_selector(
            sel, "e => e.querySelector(':scope > .ovx-handle') === null"
        ), f"{sel} must not have a drag handle"
        # direct am-grid child (viewport-fixed, not trapped by a transformed pane)
        parent = page.eval_on_selector(sel, "e => e.parentElement.className")
        assert "am-grid" in parent, f"{sel} must mount in am-grid (got {parent!r})"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [w-mmrect]: {errors[:3]}"


def test_overlay_minimap_rect_threads_through_live_state(mock_server, pw_browser):
    """Regression (item 567): minimap_rect is a TOP-LEVEL /api/state sibling, so it
    must be threaded into state.latest at every live poll site (SSE / HTTP-fallback /
    LCU poller) - exactly like liveclient. The ui_mock drive path reads
    _amMockData.minimap_rect DIRECTLY (main.js mock branch), which MASKED a live-path
    wiring gap: the foundation added the render call + the backend field but never
    threaded minimap_rect into state.latest, so over a real game renderMinimapRect
    always got null and the box stayed invisible. This drives the LIVE (non-mock) SSE
    envelope and asserts the box paints from state.latest.minimap_rect."""
    from tests.snapshot_panels.conftest import _WS_STUB

    # A live state envelope (NOT ui_mock) - the SSE handler must thread minimap_rect.
    mock_server._store["data"] = {
        "mode_key": "sr",
        "coach": {"action": "Push mid", "immediate": "Group up", "kda": "1/0/0"},
        "liveclient": {"level": 6, "game_time_s": 120},
        "minimap_rect": {"x": 1600, "y": 761, "w": 312, "h": 312, "flip": False,
                         "source": "settings", "native_w": 2560, "native_h": 1440},
    }
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?overlay=1&mode=sr",
                  wait_until="domcontentloaded", timeout=15_000)
        # The box paints only once the live SSE envelope threads minimap_rect into
        # state.latest and renderMinimapRect runs off it. Pre-fix this never
        # happened (state.latest.minimap_rect stayed undefined -> null -> hidden).
        page.wait_for_function(
            "() => { const m = document.getElementById('am-mmrect');"
            " return m && !m.hidden && m.classList.contains('ovx-widget'); }",
            timeout=10_000,
        )
        assert page.eval_on_selector("#am-mmrect", "e => e.dataset.ovxId") == "w-mmrect"
        # window-fraction placement + the +6px calibration nudge (1600/1920*1920+6).
        assert _css(page, "#am-mmrect", "left") == "1606px", "box not at the threaded x"
        assert _css(page, "#am-mmrect", "position") == "fixed"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [live minimap threading]: {errors[:3]}"


def test_overlay_zoi_threads_through_live_state(mock_server, pw_browser):
    """Regression (item 567 slice 3): zoi is a TOP-LEVEL /api/state sibling (the
    influence FILL that rides inside the slice-1 minimap box), so - exactly like
    minimap_rect - it must be threaded into state.latest at every live poll site
    (SSE / HTTP-fallback / LCU poller). The ui_mock drive path reads _amMockData.zoi
    DIRECTLY, which would MASK a live-path wiring gap. This drives the LIVE (non-mock)
    SSE envelope and asserts the ZOI canvas mounts, sizes its backing store from the
    threaded box, and renderMinimapZoi runs without error off state.latest.zoi.

    The minimap_rect block ships alongside zoi so the parent #am-mmrect box is laid
    out at a real px size (the canvas reads its width/height from the parent)."""
    from tests.snapshot_panels.conftest import _WS_STUB

    # A live state envelope (NOT ui_mock) - the SSE handler must thread BOTH the
    # minimap_rect (to size the box) and the zoi fill block.
    mock_server._store["data"] = {
        "mode_key": "sr",
        "coach": {"action": "Push mid", "immediate": "Group up", "kda": "1/0/0"},
        "liveclient": {"level": 6, "game_time_s": 120},
        "minimap_rect": {"x": 1600, "y": 761, "w": 312, "h": 312, "flip": False,
                         "source": "settings", "native_w": 2560, "native_h": 1440},
        "zoi": {
            "bubbles": [
                {"team": "blue", "cx": 0.2, "cy": 0.8, "r_frac": 0.12, "weight": 60},
                {"team": "red", "cx": 0.75, "cy": 0.25, "r_frac": 0.11, "weight": 50},
            ],
            "demarcation": {"x1": 0.0, "y1": 0.35, "x2": 1.0, "y2": 0.65,
                            "ally_side": "bottom"},
            "map_control": {"ally_control_pct": 56, "action_quadrant": "mid",
                            "line": "Map control 56%. Action mid."},
        },
    }
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?overlay=1&mode=sr",
                  wait_until="domcontentloaded", timeout=15_000)
        # The canvas paints only once the live SSE envelope threads zoi into
        # state.latest and renderMinimapZoi runs off it. The box must be visible
        # (slice-1 sized it) and the canvas backing store must be sized to the box.
        page.wait_for_function(
            "() => { const m = document.getElementById('am-mmrect');"
            " const c = document.getElementById('am-zoi-canvas');"
            " return m && !m.hidden && c && c.width > 0 && c.height > 0; }",
            timeout=10_000,
        )
        # The canvas backing store tracks the threaded box width (312px).
        cw = page.eval_on_selector("#am-zoi-canvas", "e => e.width")
        assert cw == 312, f"canvas not sized to the threaded box width: {cw}"
        # Belt-and-suspenders: the canvas is click-through (never eats a minimap click).
        assert _css(page, "#am-zoi-canvas", "pointer-events") == "none"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [live zoi threading]: {errors[:3]}"


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


def test_overlay_callouts_clamp_to_two_rows(mock_server, pw_browser):
    """RC2 P3.2 density clamp: the overlay S1 slot shows only the 2
    nearest-ETA callout rows; a third row is display:none on the HUD (the
    dashboard keeps all 3). Spec RC2_OVERLAY_CONDENSATION_SPEC section 2."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.evaluate(
            "() => {"
            "  const co = document.getElementById('rn-callouts');"
            "  co.hidden = false;"
            "  co.innerHTML ="
            " '<div class=\"rc-co-row\"><span class=\"rc-co-line\">Drake 0:30</span></div>'"
            "+'<div class=\"rc-co-row\"><span class=\"rc-co-line\">Herald 1:10</span></div>'"
            "+'<div class=\"rc-co-row\"><span class=\"rc-co-line\">Baron 9:50</span></div>';"
            "}"
        )
        assert page.locator("#rn-callouts .rc-co-row").count() == 3, (
            "fixture should mount 3 callout rows"
        )
        # First two render; the third is clamped off on the HUD.
        for n in (1, 2):
            assert _display(page, f"#rn-callouts .rc-co-row:nth-child({n})") != "none", (
                f"callout row {n} must render in overlay"
            )
        assert _display(page, "#rn-callouts .rc-co-row:nth-child(3)") == "none", (
            "3rd callout row must be clamped (display:none) in overlay"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [callouts clamp]: {errors[:3]}"


def test_overlay_choices_hit_target_44px(mock_server, pw_browser):
    """RC2 P3.3 glance-test acceptance (RC2_OVERLAY_CONDENSATION_SPEC
    section 7): the S0 A+B choice chips clear a 44px hit target at game
    distance. coach_choices.js stacks them full-width column; overlay.css
    lifts the per-chip min-height from the 42px 1920-grid floor to 44px."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.evaluate(
            "() => {"
            "  const ch = document.getElementById('rn-choices');"
            "  ch.hidden = false;"
            "  ch.innerHTML ="
            " '<button class=\"rc-chip\" data-key=\"A\">A trade</button>'"
            "+'<button class=\"rc-chip\" data-key=\"B\">B back off</button>';"
            "}"
        )
        chips = page.locator("#rn-choices .rc-chip")
        assert chips.count() == 2, "fixture should mount 2 choice chips"
        for n in range(2):
            box = chips.nth(n).bounding_box()
            assert box is not None and box["height"] >= 44, (
                f"choice chip {n} height {box and box['height']} below 44px floor"
            )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [choices hit-target]: {errors[:3]}"


def test_overlay_change_pulse_hook(mock_server, pw_browser):
    """overlay_pulse.js: when the S0 decision ARMS the pulse
    (#right-now[data-s0-pulse="1"]), a content change inside an overlay panel
    adds the .ov-pulse edge-glow to its container for ~1.2s, then drops it.
    The 2026-06-22 motion-rationing flip gates the glow on the s0-pulse arm;
    benign unarmed changes no longer pulse (see the no-pulse-when-unarmed test)."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        # Let the initial mock-render pulse window + throttle expire.
        page.wait_for_timeout(1700)
        page.evaluate(
            "() => {"
            "  const rn = document.getElementById('right-now');"
            "  if (rn) rn.dataset.s0Pulse = '1';"
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


def test_overlay_change_no_pulse_when_unarmed(mock_server, pw_browser):
    """Motion-rationing (2026-06-22 flip): a benign content change with the S0
    pulse UNARMED (no #right-now[data-s0-pulse="1"]) must NOT add .ov-pulse -
    only the emergency / urgent-cross decision pulses."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.wait_for_timeout(1700)
        page.evaluate(
            "() => {"
            "  const rn = document.getElementById('right-now');"
            "  if (rn) rn.dataset.s0Pulse = '0';"
            "  const d = document.createElement('div');"
            "  d.textContent = 'minor update';"
            "  document.getElementById('am-call-body').appendChild(d);"
            "}"
        )
        page.wait_for_timeout(800)
        assert not page.evaluate(
            "document.querySelector('.am-pane-call').classList.contains('ov-pulse')"
        ), "benign change pulsed while S0 unarmed (motion-rationing breached)"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [no-pulse]: {errors[:3]}"


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


def test_overlay_s0_pulse_rations_sustained_choices_via_producer(mock_server, pw_browser):
    """RC2 P3.3 producer-side rationing, validated live 2026-06-23 (item 598).

    The node chain tests (test_overlay_priority_rc2 / test_overlay_pulse_flip_rc2)
    drive signalFromState -> selectPrimary -> shouldPulse in isolation, and the
    DOM consumer tests above MANUALLY set #right-now[data-s0-pulse]. NEITHER
    exercises the right_now.js PRODUCER render that stamps the attribute in a live
    browser DOM. This pins that path: call the shipped renderRightNow producer
    directly (same ES-module singleton main.js uses) and read the stamp back.

    Reproduces the live read off a real SR game (Syndra vs Braum/Gragas):
    a SUSTAINED one-shot-urgent CHOICES cue stamps s0Cue="choices" s0Tier="urgent"
    s0Pulse="0" (no re-fire) - while its FRESH cross arms once (pulse="1"). That
    arm-then-ration cross is the section-5 motion-rationing the overlay relies on
    to avoid alarm fatigue."""
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
        page.goto(mock_server.url + "/?ui_mock=1&mode=sr&overlay=1",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#am-sub') && "
            "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
            timeout=10_000,
        )
        # Drive the REAL producer three times: (1) a non-choices action forces
        # _s0PrevCue off "choices"; (2) choices appear -> fresh one-shot-urgent
        # cross ARMS the pulse; (3) the same choices SUSTAIN -> rationed, no
        # re-fire. We read #right-now[data-s0-pulse] each time - the stamp the
        # production render writes (right_now.js:503-506), not a manual set.
        result = page.evaluate(
            "async () => {"
            "  const m = await import('/js/panels/right_now.js');"
            "  const rn = document.getElementById('right-now');"
            "  const read = () => ({cue: rn.dataset.s0Cue, tier: rn.dataset.s0Tier,"
            "                       pulse: rn.dataset.s0Pulse});"
            "  m.renderRightNow({action: 'Farm safe under tower'});"
            "  const a = read();"
            "  m.renderRightNow({action: 'Hold and poke at range', choices: [1]});"
            "  const b = read();"
            "  m.renderRightNow({action: 'Hold and poke at range', choices: [1]});"
            "  const c = read();"
            "  return {a, b, c};"
            "}"
        )
    finally:
        page.close()
        ctx.close()
    # (2) the FRESH choices cross arms the one-shot urgent pulse exactly once.
    assert result["b"] == {"cue": "choices", "tier": "urgent", "pulse": "1"}, (
        f"fresh choices cross must arm the pulse: {result}"
    )
    # (3) the live-validated read: a SUSTAINED choices cue stamps pulse=0 (the
    # producer rations a held cue, killing alarm fatigue).
    assert result["c"] == {"cue": "choices", "tier": "urgent", "pulse": "0"}, (
        f"sustained choices cue must NOT re-pulse: {result}"
    )
    assert not errors, f"JS errors [s0 producer]: {errors[:3]}"


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


def test_all_panels_visible_by_default(mock_server, pw_browser):
    """All-panels-accessible doctrine (operator 2026-06-28): the coach/build/threat
    quick-swap auto-hide is RETIRED. A plain ?overlay=1 shows EVERY panel - including
    the formerly reveal-only build re-rank, CDS ledger, and fight-model panes - plus
    the primary call. Per-widget .ovx-hidden (the launcher toggle / right-click hide)
    is now the only visibility gate; no panel-set keys off body[data-panelset]."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        for sel in (
            "#view-active-match .am-pane-call",
            "#view-active-match .am-pane-build",
            "#view-active-match .am-pane-cd",
            "#am-pane-ovds",
        ):
            assert _display(page, sel) != "none", (
                f"{sel} must be visible by default (all panels accessible)"
            )
        # The map pane still never paints on the HUD (not part of the field).
        assert _display(page, ".am-pane-map") == "none", "map pane should stay hidden"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "overlay_sr_all_panels.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [all panels]: {errors[:3]}"


def test_ovx_hidden_suppresses_a_panel(mock_server, pw_browser):
    """Per-widget hide is now the only visibility gate: adding .ovx-hidden to a shown
    panel (what the launcher menu toggle / right-click hide do) removes it, while its
    siblings stay - the replacement for the retired panel-set hiding."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        assert _display(page, "#view-active-match .am-pane-build") != "none"
        page.evaluate(
            "() => document.querySelector('#view-active-match .am-pane-build')"
            ".classList.add('ovx-hidden')"
        )
        assert _display(page, "#view-active-match .am-pane-build") == "none", (
            ".ovx-hidden must suppress the panel"
        )
        # A sibling pane is unaffected by another panel's hide.
        assert _display(page, "#am-pane-ovds") != "none", "sibling pane must stay shown"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [ovx-hidden]: {errors[:3]}"


def _open_overlay_scaled(pw_browser, mock_server, query, vw, vh):
    """Open the overlay route at an arbitrary viewport (RC2 4.1 multi-res)."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vw, "height": vh}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/" + query,
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    return ctx, page, errors


def test_overlay_ovscale_zooms_widget_field_at_1440(mock_server, pw_browser):
    """RC2 4.1: at 2560x1440 the Electron shell sizes the overlay WINDOW by the
    work-area scale and passes it as ovscale; the renderer sets --rc-overlay-scale
    and overlay.css applies it as a body `zoom`, so the design-px widget FIELD
    scales UP with the window (a widget's on-screen (x,y) = design-px * scale)
    instead of shrinking to a tiny corner."""
    ctx, page, errors = _open_overlay_scaled(
        pw_browser, mock_server,
        "?ui_mock=1&mode=sr&overlay=1&ovscale=1.3", 2560, 1440,
    )
    try:
        # Renderer parsed ovscale -> the CSS var + the body zoom are set.
        var = page.evaluate(
            "getComputedStyle(document.body).getPropertyValue('--rc-overlay-scale').trim()"
        )
        assert var == "1.3", f"--rc-overlay-scale not applied: {var!r}"
        assert page.evaluate("getComputedStyle(document.body).zoom") == "1.3", (
            "body zoom did not pick up the overlay scale"
        )

        # The call widget keeps its 180px design-px `left`, but the body zoom puts
        # its on-screen x at 180*1.3 ~= 234 - the FIELD zoomed up with the window.
        assert _css(page, "#view-active-match .am-pane-call", "left") == "180px"
        box = page.locator("#view-active-match .am-pane-call").bounding_box()
        assert box is not None, "call widget has no box"
        assert 224 <= box["x"] <= 244, f"scaled widget x {box['x']} not ~234 (180*1.3)"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / "overlay_sr_1440_scaled.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [ovscale 1440]: {errors[:3]}"


def test_overlay_ovscale_absent_is_baseline_noop(mock_server, pw_browser):
    """Baseline guard: no ovscale param -> --rc-overlay-scale stays unset and the
    body zoom falls back to 1, so the widget field renders at its unscaled design
    px (the call widget's eye-line default x ~= 760; zero change at 1920/100%)."""
    ctx, page, errors = _open_overlay_scaled(
        pw_browser, mock_server, "?ui_mock=1&mode=sr&overlay=1", 1920, 1080,
    )
    try:
        var = page.evaluate(
            "getComputedStyle(document.body).getPropertyValue('--rc-overlay-scale').trim()"
        )
        assert var == "", f"--rc-overlay-scale must be unset at baseline: {var!r}"
        assert page.evaluate("getComputedStyle(document.body).zoom") in ("1", "normal"), (
            "body zoom must be the baseline no-op"
        )
        box = page.locator("#view-active-match .am-pane-call").bounding_box()
        assert box is not None and 170 <= box["x"] <= 190, (
            f"baseline widget x {box and box['x']} not ~180"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [ovscale baseline]: {errors[:3]}"


def test_overlay_ovscale_out_of_band_ignored(mock_server, pw_browser):
    """Defensive: an ovscale outside the shell's [0.8,1.6] band is ignored by
    the renderer (never trust a hand-edited URL) -> baseline no-op."""
    ctx, page, errors = _open_overlay_scaled(
        pw_browser, mock_server,
        "?ui_mock=1&mode=sr&overlay=1&ovscale=2.5", 2560, 1440,
    )
    try:
        var = page.evaluate(
            "getComputedStyle(document.body).getPropertyValue('--rc-overlay-scale').trim()"
        )
        assert var == "", f"out-of-band ovscale must be ignored: {var!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [ovscale out-of-band]: {errors[:3]}"


def test_overlay_subfloor_tokens_resolve_to_game_distance_px(mock_server, pw_browser):
    """R8 (the R6 residual): the overlay sub-floor font-sizes were tokenized
    (overlay.css sec 1b --fs-ov-chip / --fs-ov-sigil). This proves the rename
    is zero pixel delta in a real browser - the overlay-scoped custom
    properties resolve to the same game-distance px the bare literals carried
    (13px chip/source/initial, 12px sigil) AND cascade to a real consumer."""
    ctx, page, errors = _open_overlay_set(pw_browser, mock_server, "threat")
    try:
        # The tokens are defined on body[data-shell="overlay"]; getComputedStyle
        # surfaces custom properties resolved at the scope root.
        chip = page.evaluate(
            "getComputedStyle(document.body).getPropertyValue('--fs-ov-chip').trim()"
        )
        sigil = page.evaluate(
            "getComputedStyle(document.body).getPropertyValue('--fs-ov-sigil').trim()"
        )
        assert chip == "13px", f"--fs-ov-chip resolved {chip!r}, expected 13px"
        assert sigil == "12px", f"--fs-ov-sigil resolved {sigil!r}, expected 12px"

        # A real consumer resolves through the token: inject a .rc-src chip
        # into the overlay DOM and confirm it computes to 13px (the selector
        # body[data-shell="overlay"] .rc-src matches any descendant).
        fs = page.evaluate(
            "() => {"
            "  const s = document.createElement('span');"
            "  s.className = 'rc-src';"
            "  s.textContent = 'src';"
            "  document.body.appendChild(s);"
            "  return getComputedStyle(s).fontSize;"
            "}"
        )
        assert fs == "13px", (
            f".rc-src computed font-size {fs!r}, expected 13px via --fs-ov-chip"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [subfloor tokens]: {errors[:3]}"


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
