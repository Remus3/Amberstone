"""
tests/snapshot_panels/test_champ_select_view.py
Champ-select VIEW snapshot coverage - ARAM + Arena (C1, 2026-06-06).

Renders the full-page champ-select view (#view-champ-select) for ARAM and
Arena against the ui_mock fixtures through the headless mock-server +
Playwright harness. This is the reproducible stand-in for the live
self-signed-HTTPS :8888 visual check: Claude_Preview cannot attach the
self-signed cert and 1-PC (ADR-011) has no separate-machine MCP visual path,
so the C-phase visual validation runs here in CI instead of as a one-off
screenshot. Mirrors test_panel_snapshots.py.

Drive path: /?ui_mock=1&mode=<mode>#champ-select. main.js boot flips
body.dataset.uiMock and clears the manual-view sticky; with an empty SSE
state the auto-derive lands on "home" (not a mid-flight game surface) so the
#champ-select hash wins. renderChampSelectView calls _csResolveLcu ->
_csMockLoad, which fetches /data/ui_mock/champ_select_<mode>.json and
re-renders, stamping #view-champ-select[data-cs-mode].

Asserts per mode: the view mounts with the right data-cs-mode, the mode-
specific structure renders (ARAM = bench-swap strip; Arena = duo row +
augment slots), the SR-only Pick & Ban card is hidden, and no unhandled JS
errors fire. Screenshots the view for the audit trail.
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

# (mode, the selector that only appears once the mock fixture has rendered
#  that mode's central pane - proves the async _csMockLoad render landed).
_MODE_CONTENT = {
    "aram": "#view-champ-select .csv-bench-cell",
    "arena": "#view-champ-select .csv-duo-cell",
}


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
    committed champion + the loaded CHAMPS index (the same limitation that
    leaves the sibling cooldown-watch card's visual capture OWED in this mock
    harness). The fetch/resolve WIRING is covered by
    tests/test_personal_build_panel_dom.py; here we drive renderPersonalBuild
    directly with a representative payload so the card paints in the REAL
    champ-select DOM + CSS context, validating the render output and
    screenshotting it for the UI-audit trail.
    """
    from tests.snapshot_panels.conftest import _PERSONAL_BUILD_FIXTURE

    ctx, page, errors = _open_champ_select(pw_browser, mock_server, "aram")
    try:
        n_rows = page.evaluate(
            """async (payload) => {
              const m = await import('/js/panels/personal_build.js');
              const block = document.getElementById('csv-personal-build');
              m.renderPersonalBuild(block, payload);
              return block.querySelectorAll('.pbw-row').length;
            }""",
            _PERSONAL_BUILD_FIXTURE,
        )
        assert n_rows == 5, f"expected 5 item rows, got {n_rows}"
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
    #csv-sugg-team-damage container is STATIC in index.html, so we only wait
    for the page DOM + the module-global renderer/fetch hooks to load."""
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
    Deterministic via a stubbed fetch helper + a synthetic ally comp (the
    mock server returns {} for the route, so we inject the payload client-
    side)."""
    ctx, page, errors = _open_team_damage_box(pw_browser, mock_server)
    try:
        # Stub the fetch, invoke the renderer, and read back the structure -
        # all in ONE synchronous evaluate so the live champ-select render
        # loop (which re-invokes the renderer with the empty real payload)
        # cannot race the readback.
        _SYNTH = """() => {
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


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
        ROOT / "web" / "data" / "ui_mock" / "champ_select_aram.json",
        ROOT / "web" / "data" / "ui_mock" / "champ_select_arena.json",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
