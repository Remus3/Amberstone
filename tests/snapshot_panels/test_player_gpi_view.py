"""
tests/snapshot_panels/test_player_gpi_view.py
Player-GPI 8-axis radar panel VISUAL snapshot coverage (item 450 S3).

The GPI radar (web/js/panels/player_gpi.js + web/css/panels/player_gpi.css)
renders the operator's cross-game profile over GET /api/player-profile?mode=sr
as an eight-spoke SVG octagon: one vertex per axis (aggression / farming /
vision / objectives / survival / tempo / versatility / consistency), the
polygon filled from the eight 0..100 scores, an overall score chip, and a
caption (mode / games / window / confidence). The panel mounts as a sibling of
the DS-profile card inside the champ-select Suggestions card (#player-gpi-panel,
hidden until showPlayerGpi() lands the first fetch).

This mirrors the C1/C2/C3 + ds-relscore CI-durable view-snapshot strategy: the
champ_select_* ui_mock fixtures do not exercise this player-level route, so we
drive the real showPlayerGpi directly against the live #player-gpi-panel mount
with a stubbed /api/player-profile payload (everything else passes through to
the mock server), then assert the radar geometry (the SVG polygon IS the hero
element) and screenshot the rendered panel.

Three states are exercised: a populated high-confidence radar (the screenshot),
the insufficient-sample empty-state, and the 503/unavailable fail-soft line.
"""
import pytest

from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Deterministic /api/player-profile payload - eight axes with distinct scores
# so the rendered data polygon must have eight vertices and the per-axis score
# chips must read the supplied values. Confidence high so the full radar (not
# the empty-state) renders.
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
        confidence: 'high', axes: AXES, overall: 55.0
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

# Insufficient-sample payload: axes empty + overall null -> the empty-state.
_GPI_STUB_INSUFFICIENT = """
(function () {
  const _f = window.fetch;
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/player-profile') >= 0) {
      const body = {
        ok: true, mode: 'sr', champion: null,
        n_games: 4, window: 20, min_games: 10,
        confidence: 'insufficient', axes: [], overall: null
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

# 503 payload: the route is down -> the panel must show the muted unavailable
# line, never a raw error string (repo Error-Handling rule).
_GPI_STUB_503 = """
(function () {
  const _f = window.fetch;
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/player-profile') >= 0) {
      return Promise.resolve(new Response(
        'service unavailable', { status: 503 }
      ));
    }
    return _f.apply(this, arguments);
  };
})();
"""


def _open_champ_select(pw_browser, mock_server, stub):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.add_init_script(stub)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    # The panel mounts in the champ-select Suggestions card; #champ-select makes
    # #view-champ-select visible so the rendered radar is screenshot-able.
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#champ-select",
        wait_until="domcontentloaded", timeout=15_000,
    )
    return ctx, page, errors


def test_player_gpi_radar_renders(mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, _GPI_STUB)

    # Drive the real panel into its live mount; the stubbed /api/player-profile
    # lands and repaints the SVG radar.
    page.evaluate(
        """async () => {
          const m = await import('/js/panels/player_gpi.js');
          if (m._resetPlayerGpi) m._resetPlayerGpi();
          m.showPlayerGpi('sr', 'player-gpi-panel');
        }"""
    )

    # Wait for the fetch onLand re-render to paint the data polygon.
    page.wait_for_function(
        "document.querySelectorAll('#player-gpi-panel .gpi-area').length > 0",
        timeout=10_000,
    )

    try:
        block = page.locator("#player-gpi-panel")
        assert block.is_visible(), "#player-gpi-panel not visible after render"

        # The data polygon is the hero element - it must carry eight vertices
        # (one per axis). points is a space-separated "x,y" list.
        pts = page.eval_on_selector(
            "#player-gpi-panel .gpi-area",
            "el => el.getAttribute('points')",
        )
        verts = [p for p in pts.strip().split(" ") if p]
        assert len(verts) == 8, f"expected 8 polygon vertices, got {len(verts)}: {pts}"

        # Eight axis labels + eight per-vertex score chips.
        labels = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-axis-label",
            "els => els.map(e => e.textContent.trim())",
        )
        assert len(labels) == 8, f"expected 8 axis labels, got {len(labels)}: {labels}"
        assert "AGGRESSION" in [s.upper() for s in labels]

        scores = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-axis-score",
            "els => els.map(e => e.textContent.trim())",
        )
        assert len(scores) == 8, f"expected 8 axis scores, got {len(scores)}"
        # The consistency axis (last) was 81.6 in the stub.
        assert "81.6" in scores, f"axis score 81.6 not rendered: {scores}"

        # The prominent overall number renders 55 (overall 55.0 -> "55").
        overall = page.eval_on_selector(
            "#player-gpi-panel .gpi-overall-num", "el => el.textContent.trim()"
        )
        assert overall == "55", f"overall chip != 55: {overall!r}"

        # The mode toggle exposes both SR + ARAM and marks SR active.
        active = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-mode.gpi-mode-on",
            "els => els.map(e => e.getAttribute('data-gpi-mode'))",
        )
        assert active == ["sr"], f"expected SR active in toggle, got {active}"

        SCREENSHOTS.mkdir(exist_ok=True)
        block.screenshot(path=str(SCREENSHOTS / "player-gpi_radar.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors: {errors[:3]}"


def test_player_gpi_insufficient_empty_state(mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(
        pw_browser, mock_server, _GPI_STUB_INSUFFICIENT
    )
    page.evaluate(
        """async () => {
          const m = await import('/js/panels/player_gpi.js');
          if (m._resetPlayerGpi) m._resetPlayerGpi();
          m.showPlayerGpi('sr', 'player-gpi-panel');
        }"""
    )
    # The empty-state line lands (no radar polygon for insufficient sample).
    page.wait_for_function(
        "document.querySelectorAll('#player-gpi-panel .gpi-msg').length > 0",
        timeout=10_000,
    )
    try:
        msg = page.eval_on_selector(
            "#player-gpi-panel .gpi-msg", "el => el.textContent.trim()"
        )
        assert "not enough games" in msg, f"empty-state text wrong: {msg!r}"
        assert "4/10" in msg, f"empty-state games read wrong: {msg!r}"
        # No radar polygon in the insufficient state.
        n_area = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-area", "els => els.length"
        )
        assert n_area == 0, "radar polygon should not render for insufficient sample"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_player_gpi_503_failsoft(mock_server, pw_browser):
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, _GPI_STUB_503)
    page.evaluate(
        """async () => {
          const m = await import('/js/panels/player_gpi.js');
          if (m._resetPlayerGpi) m._resetPlayerGpi();
          m.showPlayerGpi('sr', 'player-gpi-panel');
        }"""
    )
    page.wait_for_function(
        "document.querySelectorAll('#player-gpi-panel .gpi-msg-dim').length > 0",
        timeout=10_000,
    )
    try:
        msg = page.eval_on_selector(
            "#player-gpi-panel .gpi-msg-dim", "el => el.textContent.trim()"
        )
        # Fail-soft: a friendly muted line, NOT a raw 503 / error string.
        assert msg == "profile unavailable", f"fail-soft line wrong: {msg!r}"
        assert "503" not in msg
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
        Path(__file__).parents[2] / "web" / "js" / "panels" / "player_gpi.js",
        Path(__file__).parents[2] / "web" / "css" / "panels" / "player_gpi.css",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
