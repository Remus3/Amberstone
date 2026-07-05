"""
tests/snapshot_panels/test_view_profile_radar.py
View Profile -> GPI radar mount VISUAL snapshot coverage (player-snapshot-card
plan, Task 8).

The player-snapshot card (web/js/panels/player_snapshot.js) renders a
".ps-viewprofile" button carrying data-mode/data-window/data-match-id
(Task 5). Until Task 8 the button was inert (aria-disabled="true", Task 5's
placeholder). This suite proves the enabled button, clicked, reveals
"#player-gpi-radar" and mounts the never-before-mounted 8-axis GPI radar
(web/js/panels/player_gpi.js showPlayerGpi) for the card's profile_ref.mode -
the first production mount of that panel.

Mirrors test_player_gpi_view.py's /api/player-profile stub (the identical
8-axis payload) and test_player_snapshot_view.py's bare-fixture mount pattern
(renderPlayerSnapshot is not wired to any one page mount in this test - it is
driven directly, exactly like the card's own view test does).
"""
import json
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Same 8-axis high-confidence payload as test_player_gpi_view.py's _GPI_STUB -
# distinct per-axis scores so the polygon is unambiguously the real radar.
_GPI_STUB = """
(function () {
  const _f = window.fetch;
  const AXES = [
    {key:'aggression',  label:'Aggression',  unit:'dmg/min', scoring:'relative', higher_is_better:true,  score:52.4, recent_value:861.04, baseline_p50:819.32, sample_n:20},
    {key:'farming',     label:'Farming',     unit:'cs/min',  scoring:'relative', higher_is_better:true,  score:71.0, recent_value:7.4,    baseline_p50:6.8,    sample_n:20},
    {key:'vision',      label:'Vision',      unit:'vs/min',  scoring:'relative', higher_is_better:true,  score:38.5, recent_value:1.1,    baseline_p50:1.3,    sample_n:20},
    {key:'objectives',  label:'Objectives',  unit:'per game', scoring:'relative', higher_is_better:true, score:64.2, recent_value:3.2,    baseline_p50:2.6,    sample_n:20},
    {key:'survival',    label:'Survival',    unit:'deaths',  scoring:'relative', higher_is_better:false, score:47.0, recent_value:5.1,    baseline_p50:5.0,    sample_n:20},
    {key:'tempo',       label:'Tempo',       unit:'gold/min', scoring:'relative', higher_is_better:true, score:55.8, recent_value:402.0,  baseline_p50:388.0,  sample_n:20},
    {key:'versatility', label:'Versatility', unit:'champs',  scoring:'relative', higher_is_better:true,  score:29.3, recent_value:4.0,    baseline_p50:6.0,    sample_n:20},
    {key:'consistency', label:'Consistency', unit:'stddev',  scoring:'relative', higher_is_better:false, score:81.6, recent_value:0.9,    baseline_p50:1.4,    sample_n:20}
  ];
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/player-profile') >= 0) {
      const body = {
        ok: true, mode: 'sr', champion: null,
        n_games: 619, window: 20, min_games: 10,
        confidence: 'high', axes: AXES, overall: 55.0,
        champions: [{champion_id: 64, n_games: 20}, {champion_id: 99, n_games: 8}],
        weakest_axis: 'vision',
        tip: 'Ward more - your vision per minute is low; carry a control ward and sweep before objectives.'
      };
      return Promise.resolve(new Response(
        JSON.stringify(body),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      ));
    }
    return _f.apply(this, arguments);
  };
})();
"""

# Card model with a set profile_ref.mode - the field the click handler reads
# to call showPlayerGpi(mode, "player-gpi-radar").
_CARD_MODEL = {
    "header": {
        "name": "SamplePlayer", "rank_tier": "GOLD II", "rank_lp": 42,
        "level": 217, "streak": {"kind": "win", "n": 3},
        "champion_id": 222, "result": None,
    },
    "dial": {"value": 72, "band": "good", "label": "SR last 24h"},
    "minis": [
        {"key": "kda", "value": "3.45", "provenance": "source_truth"},
        {"key": "winrate", "value": "62%", "provenance": "source_truth"},
        {"key": "kp", "value": "58%", "provenance": "inferred"},
    ],
    "bars": [
        {"key": "income", "label": "INCOME", "score": 68.0, "provenance": "source_truth"},
        {"key": "combat", "label": "COMBAT", "score": 80.0, "provenance": "source_truth"},
        {"key": "objectives", "label": "OBJECTIVES", "score": 55.0, "provenance": "source_truth"},
        {"key": "vision", "label": "VISION", "score": 38.5, "provenance": "source_truth"},
    ],
    "tags": [
        {"label": "Aggressive", "tone": "strong"},
        {"label": "Generalist", "tone": "neutral"},
        {"label": "Visionless", "tone": "weak"},
    ],
    "profile_ref": {"mode": "sr", "window": "24h", "match_id": None},
    "confidence": "high", "sample_n": 20, "empty": False,
}


def _open_page(pw_browser, mock_server, stub=_GPI_STUB):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    from tests.snapshot_panels.conftest import _WS_STUB
    page.add_init_script(_WS_STUB)
    page.add_init_script(stub)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1", wait_until="domcontentloaded", timeout=15_000,
    )
    return ctx, page, errors


def _mount_card(page, model):
    """Create a bare #ps-fixture div and call renderPlayerSnapshot(el, model) -
    mirrors test_player_snapshot_view.py's _mount_and_render exactly, so this
    proves the delegated (document-level) click wiring in main.js, not a
    per-button listener attached at some specific host's render time."""
    page.evaluate(
        """async (model) => {
          let el = document.getElementById('ps-fixture');
          if (!el) {
            el = document.createElement('div');
            el.id = 'ps-fixture';
            document.body.appendChild(el);
          }
          const m = await import('/js/panels/player_snapshot.js');
          m.renderPlayerSnapshot(el, model);
        }""",
        model,
    )


def test_view_profile_click_mounts_gpi_radar(mock_server, pw_browser):
    ctx, page, errors = _open_page(pw_browser, mock_server)
    _mount_card(page, _CARD_MODEL)
    page.wait_for_selector('[data-testid="player-snapshot"]', timeout=10_000)
    try:
        btn = page.locator("#ps-fixture .ps-viewprofile")
        assert btn.count() == 1, "View Profile button missing"
        # Task 8 enables the button - no aria-disabled should remain.
        assert btn.get_attribute("aria-disabled") is None, (
            "View Profile button still aria-disabled after Task 8"
        )

        # Radar container starts hidden/empty (RED-state proof point).
        # critfix: the container the delegated handler resolves for a
        # scopeless #ps-fixture button is now #home-gpi-radar (the old
        # shared "#player-gpi-radar" id was renamed and split per-view;
        # #ps-fixture sits outside every scope, so the handler's
        # `|| document` fallback picks the FIRST ".player-gpi-radar" in
        # document order, which is the Home container).
        radar = page.locator("#home-gpi-radar")
        assert radar.count() == 1, "#home-gpi-radar container missing from index.html"

        btn.click()

        # Wait for the fetch onLand re-render to paint the data polygon.
        page.wait_for_function(
            "document.querySelectorAll('#home-gpi-radar svg').length > 0",
            timeout=10_000,
        )

        assert radar.is_visible(), "#home-gpi-radar stayed hidden after click"

        # The SVG polygon is the radar's hero element - eight vertices (one
        # per axis), proving the real showPlayerGpi mount fired (not a stub).
        pts = page.eval_on_selector(
            "#home-gpi-radar .gpi-area", "el => el.getAttribute('points')"
        )
        verts = [p for p in pts.strip().split(" ") if p]
        assert len(verts) == 8, f"expected 8 polygon vertices, got {len(verts)}: {pts}"

        overall = page.eval_on_selector(
            "#home-gpi-radar .gpi-overall-num", "el => el.textContent.trim()"
        )
        assert overall == "55", f"overall chip != 55: {overall!r}"

        # Mode toggle reflects the card's profile_ref.mode ("sr").
        active = page.eval_on_selector_all(
            "#home-gpi-radar .gpi-mode.gpi-mode-on",
            "els => els.map(e => e.getAttribute('data-gpi-mode'))",
        )
        assert active == ["sr"], f"expected SR active in toggle, got {active}"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#home-gpi-radar").screenshot(
            path=str(SCREENSHOTS / "view-profile_gpi-radar.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_view_profile_click_wiring_is_delegated(mock_server, pw_browser):
    """The click handler must be attached ONCE at document/body level (event
    delegation), not per-button at card-render time - a direct listener would
    be lost across the card's idempotent re-render. Proven by re-rendering the
    card with a changed model (new dataset.sig -> innerHTML rebuild wipes any
    directly-attached listener) and confirming the click STILL mounts the
    radar afterward."""
    ctx, page, errors = _open_page(pw_browser, mock_server)
    _mount_card(page, _CARD_MODEL)
    page.wait_for_selector('[data-testid="player-snapshot"]', timeout=10_000)
    try:
        # Force a rebuild: change dial.value so the JSON signature differs and
        # renderPlayerSnapshot rewrites innerHTML (any per-button listener from
        # the first render would be destroyed here).
        changed_model = dict(_CARD_MODEL)
        changed_model["dial"] = {"value": 73, "band": "good", "label": "SR last 24h"}
        _mount_card(page, changed_model)

        btn = page.locator("#ps-fixture .ps-viewprofile")
        btn.click()
        # critfix: #home-gpi-radar (see id-rename comment above).
        page.wait_for_function(
            "document.querySelectorAll('#home-gpi-radar svg').length > 0",
            timeout=10_000,
        )
        assert page.locator("#home-gpi-radar").is_visible(), (
            "radar did not mount after a post-rebuild click - "
            "listener is not delegated"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _open_last_match_real_router(pw_browser, mock_server, mode="sr"):
    """Drive the REAL page + router (mirrors test_last_match_view.py) so
    #home-overlay is genuinely display:none (the router's renderHomePanel
    adds .hidden because body.dataset.view != "home") and #pgr-snapshot-card
    is populated by the real _setHeroRoleGrade -> renderPlayerSnapshot path -
    not a bare fixture div. This is the ONLY way to reproduce the bug: a
    bare #ps-fixture mount (as _mount_card above does) is never inside any
    hidden ancestor, so it cannot demonstrate the cross-view failure."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_GPI_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    # Route /api/post-game-rubric so _setHeroRoleGrade builds a REAL
    # profile_ref.mode via _pgrInferMode(match) instead of the empty model
    # (mirrors _RUBRIC_PAYLOAD in test_last_match_view.py).
    def _fulfill_rubric(route):
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps({
                "ok": True, "match_id": "NA1_TEST", "role": "BOTTOM",
                "total_score": 72.0, "percentile_grade": "A",
                "components": {
                    "kda": 3.0, "cs_per_min": 1.2, "obj_participation": 0.8,
                    "vision": 0.5, "dpm": 2.0,
                },
                "weights_used": {
                    "kda": 1.5, "cs_per_min": 1.2, "obj_participation": 0.8,
                    "vision_score": 0.5, "damage_per_min": 1.0,
                },
            }),
        )
    page.route("**/api/post-game-rubric*", _fulfill_rubric)

    url = mock_server.url + f"/?ui_mock=1&mode={mode}#last-match"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.querySelector('#lm-mode-tag') && "
        "document.querySelector('#lm-mode-tag').textContent.trim() !== '-' && "
        "document.querySelector('#lm-mode-tag').textContent.trim() !== ''",
        timeout=10_000,
    )
    # Confirm the reproduction precondition: #home-overlay IS hidden (the
    # router genuinely hid it because the active view is last-match, not
    # home) - if this ever stops being true the bug scenario no longer
    # applies and the test below would be a false negative.
    page.wait_for_function(
        "document.getElementById('home-overlay') && "
        "document.getElementById('home-overlay').classList.contains('hidden')",
        timeout=10_000,
    )
    return ctx, page, errors


def test_view_profile_pgr_context_radar_is_visible(mock_server, pw_browser):
    """CRITICAL cross-view bug (final whole-branch review): the PGR card's
    View Profile button (#pgr-snapshot-card, #view-last-match) must mount
    the GPI radar into a container that is ACTUALLY VISIBLE, not merely
    hidden=false while a #home-overlay ancestor sits display:none. Before
    the fix this FAILS: the single shared #player-gpi-radar container lives
    inside #home-overlay (index.html ~line 120), and #home-overlay is
    display:none on the last-match view (home.css:40 .home-overlay.hidden),
    so radar.hidden=false has no visible effect - is_visible() stays False."""
    ctx, page, errors = _open_last_match_real_router(pw_browser, mock_server)
    try:
        btn = page.locator("#pgr-snapshot-card .ps-viewprofile")
        assert btn.count() == 1, "PGR View Profile button missing"

        btn.click()

        # Give the click handler + any re-render a moment to settle, then
        # assert on ACTUAL VISIBILITY (getBoundingClientRect-backed), not
        # the .hidden property - that is exactly the distinction the bug
        # hides behind (hidden=false but display:none via an ancestor).
        page.wait_for_timeout(300)

        radar = page.locator("#pgr-gpi-radar")
        if radar.count() == 0:
            # Pre-fix: no per-view PGR container exists yet: the handler
            # mounted (or tried to mount) into the single shared
            # #player-gpi-radar, which is buried in the hidden
            # #home-overlay. Assert THAT container is not visibly showing
            # the radar, which is the pre-fix failure mode.
            shared = page.locator("#player-gpi-radar")
            assert shared.count() == 1
            assert not shared.is_visible(), (
                "pre-fix expectation violated: shared #player-gpi-radar is "
                "somehow visible from the PGR view - bug may already be "
                "fixed or environment changed"
            )
            raise AssertionError(
                "#pgr-gpi-radar container does not exist (per-view radar "
                "container not yet added to #view-last-match) AND the "
                "shared #player-gpi-radar it fell back to is not visible "
                "(buried inside display:none #home-overlay) - PGR View "
                "Profile mounts the radar into an invisible container"
            )

        assert radar.is_visible(), (
            "#pgr-gpi-radar exists but is not visible after click - "
            "still mounting into a hidden-ancestor container"
        )

        pts = page.eval_on_selector(
            "#pgr-gpi-radar .gpi-area", "el => el.getAttribute('points')"
        )
        verts = [p for p in pts.strip().split(" ") if p]
        assert len(verts) == 8, f"expected 8 polygon vertices, got {len(verts)}: {pts}"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#pgr-gpi-radar").screenshot(
            path=str(SCREENSHOTS / "view-profile_pgr-gpi-radar.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_view_profile_home_context_radar_still_visible(mock_server, pw_browser):
    """Regression companion to the PGR-context test above: the Home card's
    View Profile must still mount a VISIBLE radar after the per-context fix
    (Home's own container, id renamed to #home-gpi-radar, lives inside the
    now-VISIBLE #home-overlay on the home view)."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_GPI_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1", wait_until="domcontentloaded", timeout=15_000,
    )
    try:
        # Home view's #home-overlay must be the visible one here (inverse
        # precondition of the PGR test above).
        page.wait_for_function(
            "document.getElementById('home-overlay') && "
            "!document.getElementById('home-overlay').classList.contains('hidden')",
            timeout=10_000,
        )
        _mount_card(page, _CARD_MODEL)
        page.wait_for_selector('[data-testid="player-snapshot"]', timeout=10_000)

        btn = page.locator("#ps-fixture .ps-viewprofile")
        btn.click()
        page.wait_for_function(
            "document.querySelectorAll('.player-gpi-radar svg').length > 0",
            timeout=10_000,
        )
        # #ps-fixture is a bare body-level div (not inside #home-overlay),
        # so the delegated handler's `|| document` fallback resolves the
        # first `.player-gpi-radar` in document order - the Home container.
        radar = page.locator("#home-gpi-radar")
        assert radar.count() == 1, "#home-gpi-radar container missing"
        assert radar.is_visible(), "#home-gpi-radar not visible after click"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
