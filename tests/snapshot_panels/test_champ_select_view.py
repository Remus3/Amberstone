"""
tests/snapshot_panels/test_champ_select_view.py
Champ-select VIEW snapshot coverage - SR + ARAM + Arena.

Renders the full-page champ-select view (#view-champ-select) against the
ui_mock fixtures through the headless mock-server + Playwright harness.
This is the reproducible stand-in for the live self-signed-HTTPS :8888
visual check. Mirrors test_panel_snapshots.py.

Drive path: /?ui_mock=1&mode=<mode>#champ-select. main.js boot flips
body.dataset.uiMock and clears the manual-view sticky; with an empty SSE
state the auto-derive lands on "home" (not a mid-flight game surface) so the
#champ-select hash wins. renderChampSelectView calls _csResolveLcu ->
_csMockLoad, which fetches /data/ui_mock/champ_select_<mode>.json and
re-renders, stamping #view-champ-select[data-cs-mode].

2026-07-03 QA rework (slice A, docs/qa/CHAMP_SELECT_QA_2026-07-03.md):
asserts the REMOVED elements stay absent (ghost wrappers, mood row, ally
mirror, cc-pairing, cooldown-watch, GPI, ds profile/knobs/statcheck mounts,
YOUR RECORD block) and the NEW structure renders (merged build section with
ordered-sequence strip, compact summoner-spell strip with edit affordance,
collapsed TEAM ANALYSIS cluster).
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"
CSV_JS = ROOT / "web" / "js" / "panels" / "champ_select.js"
CSV_CSS = ROOT / "web" / "css" / "panels" / "champ_select_view.css"
INDEX_HTML = ROOT / "web" / "index.html"

# (mode, the selector that only appears once the mock fixture has rendered
#  that mode's central pane - proves the async _csMockLoad render landed).
_MODE_CONTENT = {
    "sr": "#view-champ-select .csv-pb168-pick",
    "aram": "#view-champ-select .csv-bench-cell",
    "arena": "#view-champ-select .csv-duo-cell",
}

# QA 2026-07-03 slice A: selectors that must be ABSENT from the DOM after
# the rework (A2/A3/A4/A7, B12, B15, B19, B20, B22, B23).
_REMOVED_SELECTORS = [
    # A2 ghosts: hidden Assessment-card bans + pick-order wrappers.
    ".csv-sugg-bans", "#csv-sugg-bans-grid",
    ".csv-sugg-pickorder", "#csv-sugg-pickorder-body",
    # A7: dual-score ban toggle (lived inside the A2 ghost surface).
    "#csv-sugg-bs-toggle",
    # A3: mood row/buttons.
    ".csv-pb-mood-row", ".csv-pb-mood-btn",
    # A4: deprecated YOUR RECORD block.
    ".csv-pr", "#csv-sugg-your-record",
    # B15: ally-picks-by-role mirror.
    ".csv-allyroles-grid", ".csv-allyroles-row",
    # B12: CC pairing card mount.
    "#csv-sugg-cc-pairing",
    # B19: cooldown-watch card mount.
    "#csv-sugg-cooldown-watch",
    # B23: player GPI radar mount.
    "#player-gpi-panel",
    # B20/B22: DS profile / knobs / stat-check mounts.
    "#csv-sugg-ds-profile", "#csv-ds-knobs", "#csv-ds-statcheck",
]

# New structure that must be PRESENT (static mounts).
_NEW_STATIC_SELECTORS = [
    "#csv-team-analysis",
    "#csv-team-analysis #csv-ta-head",
    "#csv-team-analysis #csv-ta-body",
    "#csv-team-analysis #csv-sugg-team-damage",
    "#csv-team-analysis #csv-sugg-cc-blended-ehp-threat",
    "#csv-team-analysis #csv-sugg-cc-conditional-pressure",
    # Kept survivors.
    "#csv-sugg-ds-skill-order",
    "#csv-personal-build",
    "#csv-sugg-counter-picks",
]


def _open_champ_select(pw_browser, mock_server, mode):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home", so the
    # #champ-select hash is NOT treated as a stale game-state surface and
    # wins the view router (see main.js _viewResolveAndApply).
    mock_server._store["data"] = {}

    # Render at the spec's 1920x1080 design baseline (docs/UI_SCALE_SPEC_V2.md)
    # so the capture + no-scroll hierarchy assertions match the operator's
    # actual monitor instead of Playwright's default 1280-wide viewport.
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + f"/?ui_mock=1&mode={mode}#champ-select"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # Wait for the async mock render to land its mode-specific content.
    page.wait_for_function(
        f"document.querySelectorAll('{_MODE_CONTENT[mode]}').length > 0",
        timeout=10_000,
    )
    return ctx, page, errors


@pytest.mark.parametrize("mode", ["aram", "arena"])
def test_champ_select_view_renders(mode, mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        view = page.locator("#view-champ-select")
        assert view.is_visible(), f"#view-champ-select not visible (mode={mode})"
        assert view.get_attribute("data-cs-mode") == mode, (
            f"data-cs-mode != {mode!r} (mode={mode})"
        )

        # SR-only Pick & Ban card must be hidden in ARAM/Arena.
        assert not page.locator(".csv-card-pickban").is_visible(), (
            f"Pick & Ban card should be hidden in {mode}"
        )

        # Mode-specific structure landed.
        assert page.locator(_MODE_CONTENT[mode]).count() > 0, (
            f"mode-specific content missing (mode={mode})"
        )

        SCREENSHOTS.mkdir(exist_ok=True)
        view.screenshot(path=str(SCREENSHOTS / f"champ-select_{mode}.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_champ_select_removed_elements_absent(mode, mock_server, pw_browser):
    """QA slice A: every removed card/mount is gone from the rendered DOM."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        counts = page.evaluate(
            """(sels) => {
              const out = {};
              for (const s of sels) out[s] = document.querySelectorAll(s).length;
              return out;
            }""",
            _REMOVED_SELECTORS,
        )
        offenders = {s: n for s, n in counts.items() if n > 0}
        assert not offenders, f"removed elements still in DOM ({mode}): {offenders}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [removed/{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_champ_select_new_structure_present(mode, mock_server, pw_browser):
    """QA slice A: the new cluster + merged-build + kept mounts exist."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        counts = page.evaluate(
            """(sels) => {
              const out = {};
              for (const s of sels) out[s] = document.querySelectorAll(s).length;
              return out;
            }""",
            _NEW_STATIC_SELECTORS,
        )
        missing = {s: n for s, n in counts.items() if n != 1}
        assert not missing, f"new structure missing/duped ({mode}): {missing}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [new/{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["aram", "arena"])
def test_champ_select_merged_build_section(mode, mock_server, pw_browser):
    """B6+B7: ONE build section - the ordered-sequence strip renders INSIDE
    .csv-builds (no separate sibling bo-card) with a single push control."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, mode)
    try:
        res = page.evaluate(
            """() => {
              const view = document.getElementById('view-champ-select');
              return {
                seqInBuilds: view.querySelectorAll('.csv-builds #csv-builds-seq').length,
                seqOutside: Array.from(view.querySelectorAll('#csv-builds-seq'))
                  .filter((el) => !el.closest('.csv-builds')).length,
                pushCtrls: view.querySelectorAll('.csv-builds-push-ctrl').length,
                pushCbs: view.querySelectorAll('.csv-builds-push-cb').length,
              };
            }"""
        )
        assert res["seqInBuilds"] == 1, (
            f"ordered-sequence strip must live inside .csv-builds ({mode}): {res}"
        )
        assert res["seqOutside"] == 0, f"stray sequence strip outside builds: {res}"
        assert res["pushCtrls"] == 1, f"exactly ONE push control ({mode}): {res}"
        assert res["pushCbs"] == 3, f"Runes/Spells/Build checkboxes kept: {res}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [build-merge/{mode}]: {errors[:3]}"


def test_champ_select_compact_spell_strip(mock_server, pw_browser):
    """B5: the 9-cell strip compacts to the 2 current D/F spells + an edit
    affordance; clicking edit expands the full picker inline; picking a
    spell collapses it again."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        sec = page.locator("#csv-summspell-section")
        assert sec.count() == 1, "compact spell section missing"
        assert page.locator("#csv-summspell-section .csv-summspell-current").count() == 2, (
            "compact strip must show exactly the 2 current D/F spells"
        )
        edit = page.locator("#csv-summspell-section .csv-summspell-edit")
        assert edit.count() == 1, "edit affordance missing"
        assert page.locator("#csv-summspell-section .csv-summspell-cell").count() == 0, (
            "full picker must be collapsed by default"
        )
        # Expand: full 9-cell picker appears inline.
        edit.click()
        cells = page.locator("#csv-summspell-section .csv-summspell-cell")
        assert cells.count() == 9, f"expected 9 picker cells, got {cells.count()}"
        # Pick a spell -> collapses back to the compact 2-cell strip.
        cells.first.click()
        assert page.locator("#csv-summspell-section .csv-summspell-cell").count() == 0, (
            "picker must collapse after a pick"
        )
        assert page.locator("#csv-summspell-section .csv-summspell-current").count() == 2
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [spell-strip]: {errors[:3]}"


def test_champ_select_team_analysis_cluster(mock_server, pw_browser):
    """B8/B9/B18: the TEAM ANALYSIS cluster renders collapsed with a verdict
    header; clicking the header expands the 3 detail chips and persists the
    open state in sessionStorage."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        # The aram fixture carries allies, so the team-damage chip paints its
        # placeholder and the cluster is visible.
        page.wait_for_function(
            "!document.getElementById('csv-team-analysis').hidden",
            timeout=10_000,
        )
        res = page.evaluate(
            """() => ({
              bodyHidden: document.getElementById('csv-ta-body').hidden,
              verdict: document.getElementById('csv-ta-verdict').textContent,
            })"""
        )
        assert res["bodyHidden"] is True, "cluster must default collapsed"
        assert res["verdict"].strip() != "", "collapsed header must carry a verdict line"
        page.locator("#csv-ta-head").click()
        res2 = page.evaluate(
            """() => ({
              bodyHidden: document.getElementById('csv-ta-body').hidden,
              stored: sessionStorage.getItem('csv-ta-open'),
            })"""
        )
        assert res2["bodyHidden"] is False, "click must expand the detail chips"
        assert res2["stored"] == "1", "open state must persist via sessionStorage"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [team-analysis]: {errors[:3]}"


def test_champ_select_aram_bench_strip(mock_server, pw_browser):
    """ARAM ships a 10-champion bench-swap strip from the fixture bench[]."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        cells = page.locator("#view-champ-select .csv-bench-cell")
        assert cells.count() == 10, (
            f"expected 10 bench cells, got {cells.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [aram bench]: {errors[:3]}"


def test_champ_select_arena_augments(mock_server, pw_browser):
    """Arena central pane renders the augment slot scaffold (3 slots)."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "arena")
    try:
        slots = page.locator("#view-champ-select .csv-augment-slot")
        assert slots.count() >= 1, "expected at least one augment slot"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [arena augments]: {errors[:3]}"


def test_personal_build_card_renders(mock_server, pw_browser):
    """The personal best-build card renders its ranked item rows + CSS.

    The live fetch -> resolveChampNames -> render path is render-gated on a
    committed champion + the loaded CHAMPS index. The fetch/resolve WIRING is
    covered by tests/test_personal_build_panel_dom.py; here we drive
    renderPersonalBuild directly with a representative payload so the card
    paints in the REAL champ-select DOM + CSS context, validating the render
    output and screenshotting it for the UI-audit trail.
    """
    from tests.snapshot_panels.conftest import _PERSONAL_BUILD_FIXTURE

    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        counts = page.evaluate(
            """async (payload) => {
              const m = await import('/js/panels/personal_build.js');
              const block = document.getElementById('csv-personal-build');
              m.renderPersonalBuild(block, payload);
              return {
                rows: block.querySelectorAll('.pbw-row').length,
                pips: block.querySelectorAll('.pbw-row[data-usual="1"]').length,
                usual: block.querySelectorAll('.pbw-usual-build').length,
              };
            }""",
            _PERSONAL_BUILD_FIXTURE,
        )
        assert counts["rows"] == 5, f"expected 5 item rows, got {counts['rows']}"
        # R34: 4 of the 5 ranked items are in most_common_build -> 4 usual pips,
        # and the popular-build summary line renders.
        assert counts["pips"] == 4, f"expected 4 usual-build pips, got {counts['pips']}"
        assert counts["usual"] == 1, "popular-build summary line missing"
        # R34: the survivorship insight helper across all four branches.
        kinds = page.evaluate(
            """async () => {
              const m = await import('/js/panels/personal_build.js');
              const f = m.__test._usualBuildInsight;
              const mk = (items, usual) => ({items, most_common_build: usual});
              return {
                swap: f(mk([{item_id:1,name:'A',lift:0.06},
                            {item_id:2,name:'B',lift:-0.05}], [2])),
                winner: f(mk([{item_id:1,name:'A',lift:0.06}], [])),
                loser: f(mk([{item_id:2,name:'B',lift:-0.05}], [2])),
                none: f(mk([{item_id:2,name:'B',lift:0.0}], [2])),
              };
            }"""
        )
        assert kinds["swap"]["kind"] == "swap", kinds["swap"]
        assert kinds["winner"]["kind"] == "winner", kinds["winner"]
        assert kinds["loser"]["kind"] == "loser", kinds["loser"]
        assert kinds["none"] is None, kinds["none"]
        block = page.locator("#csv-personal-build")
        assert block.is_visible(), "personal-build card not visible"
        # inner_text uppercases the header (CSS text-transform), so match
        # case-insensitively.
        text = block.inner_text()
        assert "your best build" in text.lower(), "card header missing"
        assert "Infinity Edge" in text, "top item missing"
        SCREENSHOTS.mkdir(exist_ok=True)
        block.screenshot(
            path=str(SCREENSHOTS / "champ-select_personal-build.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [personal-build]: {errors[:3]}"


def _open_counter_box(pw_browser, mock_server):
    """Lighter open for the SR counter-picks box.

    The #csv-sugg-counter-picks container is STATIC in index.html, so unlike
    _open_champ_select we do NOT wait for any async mode-specific render to
    land - we only need the page DOM + the global champ_select.js helpers
    loaded. Drive SR mode so the SR suggestions stack (with the counters
    box) is the active surface. domcontentloaded is sufficient.
    """
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + "/?ui_mock=1&mode=sr#champ-select"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    # The renderer + fetch helper are module-global; wait for them to exist.
    page.wait_for_function(
        "typeof window._csvRenderCounterPicks === 'function'"
        " && typeof window._csvFetchCounterPicks === 'function'",
        timeout=10_000,
    )
    return ctx, page, errors


def test_champ_select_counter_pick_hero(mock_server, pw_browser):
    """LIFT 1a: counters[0] renders as a single HERO card; counters[1..4]
    render as a compact secondary list. Deterministic via a stubbed fetch
    helper + a synthetic enemy comp (the mock server returns {} for the
    counter-picks endpoint, so we inject the payload client-side)."""
    ctx, page, errors = _open_counter_box(pw_browser, mock_server)
    try:
        # Stub the fetch helper, invoke the renderer, and read back the
        # resulting structure - all inside ONE synchronous evaluate. The
        # live champ-select render loop re-invokes _csvRenderCounterPicks on
        # its own schedule with the (empty) real payload, so reading the DOM
        # through separate async Playwright locators races that re-render.
        # Capturing the counts atomically in-page removes the race.
        _SYNTH = """() => {
              window._csvFetchCounterPicks = function () {
                return {
                  ok: true,
                  counters: [
                    {champId: 103, name: 'Ahri',   note: 'counters 3 of their comp', counters_count: 3},
                    {champId: 1,   name: 'Annie',  note: 'counters Zed'},
                    {champId: 64,  name: 'LeeSin', note: 'counters Yasuo'},
                    {champId: 84,  name: 'Akali',  note: 'counters Lux'},
                    {champId: 99,  name: 'Lux',    note: 'counters Vi'}
                  ]
                };
              };
              window._csvRenderCounterPicks({
                their_team: [{championId: 238}],
                my_team: [],
                bans: {my_team: [], their_team: []}
              });
            }"""
        res = page.evaluate(
            _SYNTH[:-1]  # drop the closing brace to splice in the readback
            + """
              const box = document.getElementById('csv-sugg-counter-picks');
              const hero = box.querySelectorAll('.csv-counter-hero');
              const rows = box.querySelectorAll(
                '.csv-counter-secondary .csv-counter-pick');
              const h = (el) => el.getBoundingClientRect().height;
              return {
                heads: box.querySelectorAll('.csv-counter-head').length,
                heroCount: hero.length,
                heroText: hero.length ? hero[0].innerText : '',
                heroHeight: hero.length ? h(hero[0]) : 0,
                secondaryRows: rows.length,
                minRowHeight: rows.length
                  ? Math.min.apply(null, Array.from(rows, h)) : 0,
                hidden: box.hidden,
              };
            }"""
        )

        assert res["heads"] == 1, (
            "PICK INTO THIS COMP header must be preserved"
        )
        assert res["heroCount"] == 1, (
            f"expected exactly 1 hero card, got {res['heroCount']}"
        )
        assert "Ahri" in res["heroText"], (
            f"hero must surface the top counter (Ahri); got {res['heroText']!r}"
        )
        assert res["secondaryRows"] == 4, (
            f"expected exactly 4 secondary rows, got {res['secondaryRows']}"
        )
        assert res["hidden"] is False, "counter box must be visible when populated"
        # Hit-target rule: hero + every secondary row >= 44px tall.
        assert res["heroHeight"] >= 44, (
            f"hero card must be >= 44px tall, got {res['heroHeight']}"
        )
        assert res["minRowHeight"] >= 44, (
            f"every secondary row must be >= 44px tall, got {res['minRowHeight']}"
        )

        # Idempotency: re-invoking the renderer with the same inputs yields
        # byte-identical DOM (full innerHTML rebuild each call).
        html_pair = page.evaluate(
            _SYNTH[:-1]
            + """
              const box = document.getElementById('csv-sugg-counter-picks');
              const a = box.innerHTML;
              window._csvRenderCounterPicks({
                their_team: [{championId: 238}],
                my_team: [], bans: {my_team: [], their_team: []}});
              return [a, box.innerHTML];
            }"""
        )
        assert html_pair[0] == html_pair[1], (
            "renderer must be idempotent (identical DOM on re-render)"
        )

        # Final synchronous re-render, then screenshot in the same tick for
        # the audit trail (before the live loop can overwrite).
        page.evaluate(_SYNTH)
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#csv-sugg-counter-picks").screenshot(
            path=str(SCREENSHOTS / "champ-select_counter-hero.png")
        )
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [counter-hero]: {errors[:3]}"


def _open_team_damage_box(pw_browser, mock_server):
    """Sibling of _open_counter_box for the LIFT 1b team-damage meter. The
    #csv-sugg-team-damage container is STATIC in index.html (inside the
    TEAM ANALYSIS cluster), so we only wait for the page DOM + the
    module-global renderer/fetch hooks to load."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    url = mock_server.url + "/?ui_mock=1&mode=sr#champ-select"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "typeof window._csvRenderTeamDamage === 'function'"
        " && typeof window._csvFetchTeamDamage === 'function'",
        timeout=10_000,
    )
    return ctx, page, errors


def test_champ_select_team_damage_meter(mock_server, pw_browser):
    """LIFT 1b: the ally AD/AP damage-lean meter renders a dual-color bar
    whose segment widths reflect physical_pct / magical_pct, a text label
    carrying "AD <n>%" + "AP <n>%", a >=44px section, and an idempotent DOM.
    Deterministic via a stubbed fetch helper + a synthetic ally comp. The
    meter now lives inside the collapsed TEAM ANALYSIS cluster, so the
    harness un-hides the cluster + its body before measuring."""
    ctx, page, errors = _open_team_damage_box(pw_browser, mock_server)
    try:
        # Stub the fetch, invoke the renderer, and read back the structure -
        # all in ONE synchronous evaluate so the live champ-select render
        # loop (which re-invokes the renderer with the empty real payload)
        # cannot race the readback.
        _SYNTH = """() => {
              const ta = document.getElementById('csv-team-analysis');
              if (ta) ta.hidden = false;
              const tb = document.getElementById('csv-ta-body');
              if (tb) tb.hidden = false;
              window._csvFetchTeamDamage = function () {
                return {
                  ok: true, n_champs: 3,
                  physical_pct: 70, magical_pct: 30,
                  per_champ: [
                    {champId: 266, attack: 8, magic: 3, lean: 'AD'},
                    {champId: 64,  attack: 8, magic: 3, lean: 'AD'},
                    {champId: 103, attack: 3, magic: 8, lean: 'AP'}
                  ]
                };
              };
              window._csvRenderTeamDamage({
                my_team: [
                  {championId: 266}, {championId: 103}, {championId: 64}
                ],
                their_team: [],
                bans: {my_team: [], their_team: []}
              });
            }"""
        res = page.evaluate(
            _SYNTH[:-1]  # drop the closing brace to splice in the readback
            + """
              const box = document.getElementById('csv-sugg-team-damage');
              const ad = box.querySelector('.csv-tdmg-seg-ad');
              const ap = box.querySelector('.csv-tdmg-seg-ap');
              const label = box.querySelector('.csv-tdmg-label');
              return {
                heads: box.querySelectorAll('.csv-tdmg-head').length,
                adWidth: ad ? ad.style.width : '',
                apWidth: ap ? ap.style.width : '',
                labelText: label ? label.innerText : '',
                sectionHeight: box.getBoundingClientRect().height,
                hidden: box.hidden,
              };
            }"""
        )

        assert res["heads"] == 1, "TEAM DAMAGE LEAN header must be present"
        assert res["adWidth"] == "70%", (
            f"AD segment width must reflect 70%, got {res['adWidth']!r}"
        )
        assert res["apWidth"] == "30%", (
            f"AP segment width must reflect 30%, got {res['apWidth']!r}"
        )
        assert "AD 70%" in res["labelText"], (
            f"label must contain 'AD 70%', got {res['labelText']!r}"
        )
        assert "AP 30%" in res["labelText"], (
            f"label must contain 'AP 30%', got {res['labelText']!r}"
        )
        assert res["hidden"] is False, "meter must be visible when populated"
        assert res["sectionHeight"] >= 44, (
            f"section must be >= 44px tall, got {res['sectionHeight']}"
        )

        # Idempotency: re-invoking with the same inputs yields byte-identical
        # DOM (full innerHTML rebuild each call).
        html_pair = page.evaluate(
            _SYNTH[:-1]
            + """
              const box = document.getElementById('csv-sugg-team-damage');
              const a = box.innerHTML;
              window._csvRenderTeamDamage({
                my_team: [
                  {championId: 266}, {championId: 103}, {championId: 64}],
                their_team: [], bans: {my_team: [], their_team: []}});
              return [a, box.innerHTML];
            }"""
        )
        assert html_pair[0] == html_pair[1], (
            "renderer must be idempotent (identical DOM on re-render)"
        )

        # Final synchronous re-render, then screenshot in the same tick for
        # the audit trail (before the live loop can overwrite).
        page.evaluate(_SYNTH)
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#csv-sugg-team-damage").screenshot(
            path=str(SCREENSHOTS / "champ-select_team-damage.png")
        )
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [team-damage]: {errors[:3]}"


# -- QA slice A source-level regression guards ------------------------------

def _js_src():
    return CSV_JS.read_text(encoding="utf-8")


def test_capgap_mode_vocab_aligned():
    """A1: the capability-gap fetch derives its mode from the canonical
    _csvDsModeFor vocabulary (SR/ARAM/ARENA - queue 2400 = ARAM) instead of
    a bespoke KIWI mapping that disagreed with _csvDetectMode."""
    src = _js_src()
    start = src.index("function _csvRenderCapabilityGap(")
    end = src.index("\nfunction ", start + 1)
    body = src[start:end]
    assert "KIWI" not in body, "capability-gap renderer must not send KIWI"
    assert "_csvDsModeFor" in body, (
        "capability-gap renderer must derive mode via _csvDsModeFor"
    )


def test_mood_state_fully_removed():
    """A3: mood buttons, sessionStorage mood state, and the client-side
    mood filter are gone. Recs = raw top-3 by score + LAST."""
    src = _js_src()
    for needle in ("csv-pb-mood", "_csvMoodGet", "_csvMoodSet",
                   "_CSV_MOOD_LABELS", "csv-mood", "&mood="):
        assert needle not in src, f"mood residue in champ_select.js: {needle}"
    css = CSV_CSS.read_text(encoding="utf-8")
    assert "csv-pb-mood" not in css, "mood CSS block must be removed"


def test_ghost_wrappers_and_dead_paths_removed():
    """A2/A7/A4/A6 + B12/B19/B20/B22/B23 source-level guards."""
    src = _js_src()
    for needle in (
        # A2: ghost bans grid + pick-order advisory + their fetches.
        "csv-sugg-bans-grid", "csv-sugg-pickorder-body",
        "_csvFetchBanSuggestions", "_CSV_BANSUGG_CACHE",
        "_CSV_PICKORDER_TIPS",
        # A7: dual-score ban toggle.
        "fetchBanSuggest", "renderBanSuggestModeChip", "csv-sugg-bs-toggle",
        # A4: deprecated YOUR RECORD path.
        "personal-record", "_CSV_PR_CACHE", "_csvRenderPersonalRecordBlock",
        # A6: dead timer tick.
        "_csvSetupTimerTick",
        # B15: ally mirror.
        "_csvRenderAllyRolesHtml", "csv-allyroles",
        # B12 / B19 / B23 / B20 / B22 call sites.
        "fetchCcPairing", "renderCcPairing",
        "fetchCooldownWatch", "renderCooldownWatch",
        "showPlayerGpi",
        "renderDsProfileForChampSelect", "renderDsKnobs", "renderDsStatcheck",
        # B6+B7: the standalone card renderer is replaced by the merged strip.
        "buildOrderCardHtml",
    ):
        assert needle not in src, f"dead path residue in champ_select.js: {needle}"
    # B21: DS skill order is the ONE DS card that stays.
    assert "renderDsSkillOrderForChampSelect" in src, "DS skill order must stay"
    # A4 note: the enemy WR slot is a DIFFERENT feature and must stay, now
    # fed by /api/personal-vs.
    assert "csv-enemy-wr-slot" in src, "enemy WR slot must stay"
    assert "/api/personal-vs" in src, "enemy WR slot must ride /api/personal-vs"
    # Index.html mounts for removed cards are gone; skill order mount stays.
    html = INDEX_HTML.read_text(encoding="utf-8")
    for needle in ("csv-sugg-cooldown-watch", "csv-sugg-cc-pairing",
                   "player-gpi-panel", "csv-sugg-ds-profile",
                   "csv-ds-knobs", "csv-ds-statcheck", "csv-sugg-bs-toggle"):
        assert needle not in html, f"removed mount residue in index.html: {needle}"
    assert "csv-sugg-ds-skill-order" in html, "skill-order mount must stay"
    assert "csv-team-analysis" in html, "TEAM ANALYSIS cluster mount missing"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "champ_select_sr.json",
        ROOT / "web" / "data" / "ui_mock" / "champ_select_aram.json",
        ROOT / "web" / "data" / "ui_mock" / "champ_select_arena.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
