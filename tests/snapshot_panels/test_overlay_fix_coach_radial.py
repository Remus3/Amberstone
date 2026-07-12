"""
tests/snapshot_panels/test_overlay_fix_coach_radial.py

Rendered-pixel regressions for the 2026-07-12 overlay-fix slice (operator flagged
three defects from live in-game screenshots):

  #1 the CALL macro coach rendered a leaked markdown TABLE as a raw-pipe WALL
     (| FIELD | DECISION | |---|---| ...) - now _parseCoachTable + _line lay it out
     as clean label:value rows (no pipes, bounded height);
  #2 the right-click item radial's five wedges OVERLAPPED in the old 140px ring
     (center MUTE over KEEP/LATE) - now a 210x160 ring + a compact 44px MUTE hub
     separate every wedge with no overlap, each >= the 42px hit floor;
  #3 the in-game BUILD panel's 7-icon LIVE row overflowed the 380px widget (the
     7th pick clipped) - now --ovx-w:412 fits all 7 on one line with no overflow,
     so no scrollbar eats the bottom edge and the panel sits flush.

Harness: the shared conftest mock_server + pw_browser, driven through the overlay
route (/?ui_mock=1&mode=sr&overlay=1) exactly like test_overlay_view.py.
"""


def _open_overlay(pw_browser, mock_server, query="?ui_mock=1&mode=sr&overlay=1"):
    from tests.snapshot_panels.conftest import _WS_STUB

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
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    return ctx, page, errors


# --- #1 coach markdown-table render ----------------------------------------

_TABLE_ACTION = (
    "DEFEND & SETUP TEAMFIGHT | FIELD | DECISION | |------|--------| "
    "| WAVE | HOLD/THIN - DO NOT PUSH, keep minions mid | "
    "| OBJECTIVE | DRAKE + BARON BOTH LIVE - contest drake first | "
    "| FIGHT RULE | ONLY TRADE IF ALL 4 ALLIES ARE VISIBLE |"
)


def _render_action(page, action):
    page.evaluate(
        """async ({action}) => {
            const m = await import('/js/panels/active_match.js');
            m.renderActiveMatch(
                {champion:'Jinx', game_time:'18:20', level:13, action:action,
                 immediate:'Back off - Yi respawn 47s', objective:'Drake 0:45',
                 next:'Baron soon'},
                {mode:'sr', lcuPhase:'InProgress'});
        }""",
        {"action": action},
    )
    page.wait_for_timeout(150)


def test_coach_markdown_table_renders_as_clean_rows(mock_server, pw_browser):
    """A leaked `| FIELD | DECISION |` table in the ACTION field renders as clean
    label:value sub-rows - no raw pipes, no |---| scaffolding - with the ACTION
    band glyph preserved on the headline verb, and bounded in height (not a wall)."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        _render_action(page, _TABLE_ACTION)
        info = page.eval_on_selector(
            '#am-call-body > div[data-call-line="action"]',
            """el => {
                const r = el.getBoundingClientRect();
                const px = (n) => n ? Math.round(parseFloat(getComputedStyle(n).fontSize)) : 0;
                const sub = el.querySelector('.am-call-table > div');
                const head = el.querySelector('.am-call-thead');
                return {
                    isTable: el.dataset.callTable === '1',
                    hasPipe: el.textContent.indexOf('|') >= 0,
                    hasDashRun: /---/.test(el.textContent),
                    subRows: el.querySelectorAll('.am-call-table > div').length,
                    glyph: el.querySelectorAll('.am-call-glyph').length,
                    band: el.dataset.callBand || '',
                    height: Math.round(r.height),
                    titleFs: px(head),
                    subFs: px(sub),
                    text: el.textContent,
                };
            }""",
        )
        assert info["isTable"], "the leaked table was not detected/reformatted"
        assert not info["hasPipe"], f"raw pipe leaked into the render: {info['text']!r}"
        assert not info["hasDashRun"], "the |---| separator leaked into the render"
        assert info["subRows"] == 3, (
            f"expected WAVE/OBJECTIVE/FIGHT RULE = 3 sub-rows, got {info['subRows']}"
        )
        # ACTION band channel preserved (glyph on the headline verb).
        assert info["glyph"] == 1, "the ACTION band glyph must survive the table path"
        assert info["band"], "the ACTION row must still carry a data-call-band"
        # The tactical content survives the reformat (not dropped).
        assert "WAVE" in info["text"] and "FIGHT RULE" in info["text"]
        assert "HOLD/THIN" in info["text"]
        # Bounded: the 2-line clamp + compact overlay scale keep it well under a
        # full-height wall (the raw-pipe render was ~400px+).
        assert info["height"] <= 240, (
            f"reformatted table still too tall ({info['height']}px) - clamp not applied"
        )
        # Compact overlay scale (not the base --fs-md 22 / --fs-sm 18 dashboard
        # sizes): the title matches the plain ACTION verb, rows sit a rung below,
        # and the title never reads smaller than its own rows (hierarchy).
        assert info["subFs"] <= 15, (
            f"table rows at {info['subFs']}px - not the compact overlay scale"
        )
        assert info["titleFs"] <= 16 and info["titleFs"] >= info["subFs"], (
            f"table title {info['titleFs']}px breaks the title>=row hierarchy"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [coach table]: {errors[:3]}"


def test_plain_coach_action_unchanged(mock_server, pw_browser):
    """Guard: a normal (non-table) ACTION string still renders on the plain path -
    no table markup, band glyph intact, verb text present."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        _render_action(page, "Push mid and roam bot for Dragon")
        info = page.eval_on_selector(
            '#am-call-body > div[data-call-line="action"]',
            """el => ({
                isTable: el.dataset.callTable === '1',
                glyph: el.querySelectorAll('.am-call-glyph').length,
                subRows: el.querySelectorAll('.am-call-table > div').length,
                text: el.textContent,
            })""",
        )
        assert not info["isTable"], "a plain action must not take the table path"
        assert info["subRows"] == 0, "a plain action must not emit table sub-rows"
        assert info["glyph"] == 1, "the plain ACTION band glyph must render"
        assert "Push mid and roam" in info["text"]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [plain action]: {errors[:3]}"


# --- #2 item radial wedge geometry -----------------------------------------

def test_item_radial_wedges_do_not_overlap(mock_server, pw_browser):
    """The right-click radial opens a 5-wedge ring whose wedges never overlap and
    each clears the 42px hit floor, with MUTE a compact dead-center hub (Kurtenbach:
    the four ordering actions on the cardinal axes, MUTE off them in the center)."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        wedges = page.evaluate(
            """async () => {
                const m = await import('/js/lib/overlay_item_radial.js');
                const anchor = document.createElement('div');
                anchor.style.cssText = 'position:fixed;left:900px;top:520px;width:40px;height:40px;';
                document.body.appendChild(anchor);
                m.installItemRadial(anchor, 3031, () => {});
                anchor.dispatchEvent(new MouseEvent('contextmenu',
                    {bubbles:true, clientX:900, clientY:520}));
                await new Promise(r => setTimeout(r, 60));
                const ring = document.getElementById('rc-item-radial');
                const out = {};
                ring.querySelectorAll('.rc-radial-wedge').forEach(w => {
                    const r = w.getBoundingClientRect();
                    out[w.getAttribute('data-action')] = {
                        x: r.left, y: r.top, w: r.width, h: r.height,
                        cx: r.left + r.width / 2, cy: r.top + r.height / 2};
                });
                return out;
            }"""
        )
        assert set(wedges) == {"earlier", "later", "defer", "keep", "silence"}, (
            f"expected 5 named wedges, got {sorted(wedges)}"
        )

        def overlaps(a, b):
            ox = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            oy = min(a["y"] + a["h"], b["y"] + b["h"]) - max(a["y"], b["y"])
            return ox > 0.5 and oy > 0.5

        keys = list(wedges)
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                assert not overlaps(wedges[keys[i]], wedges[keys[j]]), (
                    f"wedge {keys[i]} overlaps {keys[j]}"
                )
        # Every wedge clears the 42px hit-target floor (tokens.css --hit-min).
        for a, r in wedges.items():
            assert r["w"] >= 42 and r["h"] >= 42, (
                f"wedge {a} ({r['w']:.0f}x{r['h']:.0f}) below the 42px hit floor"
            )
        # Kurtenbach layout: MUTE dead-center; EARLY above it, DEFER below, KEEP
        # left, LATE right (cardinal axes), MUTE the most compact (a hub).
        c = wedges["silence"]
        assert wedges["earlier"]["cy"] < c["cy"] < wedges["defer"]["cy"], "N/S axis wrong"
        assert wedges["keep"]["cx"] < c["cx"] < wedges["later"]["cx"], "W/E axis wrong"
        assert c["w"] <= min(
            wedges[k]["w"] for k in ("earlier", "later", "defer", "keep")
        ), "MUTE hub should be the most compact wedge"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [radial geometry]: {errors[:3]}"


# --- #3 build panel 7-icon row width ---------------------------------------

_PICKS7 = [
    {"name": n, "item_id": i, "delta_dps": d, "scorer": "carry"}
    for n, i, d in [
        ("Kraken Slayer", 6672, 49), ("Infinity Edge", 3031, 39),
        ("Lord Dominik's Regards", 3036, 35), ("Bloodthirster", 3072, 30),
        ("Rapid Firecannon", 3094, 29), ("Guardian Angel", 3026, 29),
        ("Mortal Reminder", 3033, 27),
    ]
]


def test_build_seven_icon_row_has_no_horizontal_overflow(mock_server, pw_browser):
    """The in-game BUILD widget must fit a full 7-icon LIVE row on one line: the
    strip's scrollWidth <= clientWidth (no clipped 7th icon / overflow scrollbar),
    and the widget is the widened 412px that actually holds 7 cells."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.evaluate(
            """async ({picks}) => {
                const m = await import('/js/panels/active_match.js');
                m.renderActiveMatch(
                    {champion:'Jinx', game_time:'18:20', level:13, action:'Group mid',
                     immediate:'x', objective:'y', next:'z',
                     daemon_slayer_picks:picks},
                    {mode:'sr', lcuPhase:'InProgress'});
            }""",
            {"picks": _PICKS7},
        )
        page.wait_for_timeout(180)
        strip = page.eval_on_selector(
            "#view-active-match .am-pane-build .bm-strip",
            """s => ({scrollW: s.scrollWidth, clientW: s.clientWidth,
                     kids: s.children.length})""",
        )
        assert strip["kids"] == 7, f"expected the 7-pick LIVE row, got {strip['kids']}"
        assert strip["scrollW"] <= strip["clientW"] + 1, (
            f"7-icon row overflows: scrollWidth {strip['scrollW']} > "
            f"clientWidth {strip['clientW']} (7th icon clipped)"
        )
        # The panel itself must not carry a scroll on either axis at 7 picks.
        pane = page.eval_on_selector(
            "#view-active-match .am-pane-build",
            """el => ({vScroll: el.scrollHeight > el.clientHeight + 1,
                      hScroll: el.scrollWidth > el.clientWidth + 1,
                      w: getComputedStyle(el).width})""",
        )
        assert not pane["hScroll"], "build pane has a horizontal scrollbar at 7 picks"
        assert not pane["vScroll"], "build pane has a vertical scrollbar at 7 picks"
        assert pane["w"] == "412px", f"w-build not widened to 412px (got {pane['w']})"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [build width]: {errors[:3]}"


def test_build_panel_sits_flush_at_bottom(mock_server, pw_browser):
    """#4: dragged into the lower half the tall BUILD widget bottom-anchors and
    hugs its content (no overflow dead-space) so it can sit flush at the bottom -
    the 7-icon width fix removes the overflow that stopped this."""
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.evaluate(
            """async ({picks}) => {
                const m = await import('/js/panels/active_match.js');
                m.renderActiveMatch(
                    {champion:'Jinx', game_time:'18:20', level:13, action:'Group mid',
                     immediate:'x', objective:'y', next:'z', daemon_slayer_picks:picks},
                    {mode:'sr', lcuPhase:'InProgress'});
                const L = await import('/js/lib/overlay_layout.js');
                const el = document.querySelector('#view-active-match .am-pane-build');
                L._internals._setLayout({'w-build': {x: 70, y: 860}});
                L._internals._applyPos(el,
                    L._internals._posFor(L._internals.WIDGETS.find(w => w.id === 'w-build')));
            }""",
            {"picks": _PICKS7},
        )
        page.wait_for_timeout(180)
        m = page.eval_on_selector(
            "#view-active-match .am-pane-build",
            """el => {
                const r = el.getBoundingClientRect();
                let cb = 0;
                for (const c of el.children) {
                    const cr = c.getBoundingClientRect();
                    if (cr.bottom > cb) cb = cr.bottom;
                }
                return {contentGapBelow: Math.round(r.bottom - cb),
                        bottomCss: getComputedStyle(el).bottom,
                        vScroll: el.scrollHeight > el.clientHeight + 1,
                        hScroll: el.scrollWidth > el.clientWidth + 1};
            }""",
        )
        # Bottom-anchored (the tall-widget clamp already in overlay_layout).
        assert m["bottomCss"] == "16px", (
            f"tall build widget should bottom-anchor (got bottom={m['bottomCss']})"
        )
        # Box hugs content (no tall empty container tail) + no scrollbars.
        assert m["contentGapBelow"] <= 12, (
            f"build box not hugging content (gap {m['contentGapBelow']}px)"
        )
        assert not m["vScroll"] and not m["hScroll"], "scrollbar dead-space at bottom"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [build flush]: {errors[:3]}"
