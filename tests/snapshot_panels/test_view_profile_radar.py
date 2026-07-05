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
        radar = page.locator("#player-gpi-radar")
        assert radar.count() == 1, "#player-gpi-radar container missing from index.html"

        btn.click()

        # Wait for the fetch onLand re-render to paint the data polygon.
        page.wait_for_function(
            "document.querySelectorAll('#player-gpi-radar svg').length > 0",
            timeout=10_000,
        )

        assert radar.is_visible(), "#player-gpi-radar stayed hidden after click"

        # The SVG polygon is the radar's hero element - eight vertices (one
        # per axis), proving the real showPlayerGpi mount fired (not a stub).
        pts = page.eval_on_selector(
            "#player-gpi-radar .gpi-area", "el => el.getAttribute('points')"
        )
        verts = [p for p in pts.strip().split(" ") if p]
        assert len(verts) == 8, f"expected 8 polygon vertices, got {len(verts)}: {pts}"

        overall = page.eval_on_selector(
            "#player-gpi-radar .gpi-overall-num", "el => el.textContent.trim()"
        )
        assert overall == "55", f"overall chip != 55: {overall!r}"

        # Mode toggle reflects the card's profile_ref.mode ("sr").
        active = page.eval_on_selector_all(
            "#player-gpi-radar .gpi-mode.gpi-mode-on",
            "els => els.map(e => e.getAttribute('data-gpi-mode'))",
        )
        assert active == ["sr"], f"expected SR active in toggle, got {active}"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#player-gpi-radar").screenshot(
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
        page.wait_for_function(
            "document.querySelectorAll('#player-gpi-radar svg').length > 0",
            timeout=10_000,
        )
        assert page.locator("#player-gpi-radar").is_visible(), (
            "radar did not mount after a post-rebuild click - "
            "listener is not delegated"
        )
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
