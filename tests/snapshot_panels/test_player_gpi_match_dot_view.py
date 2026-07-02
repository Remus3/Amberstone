"""
tests/snapshot_panels/test_player_gpi_match_dot_view.py
Player-GPI "this match" dot-overlay VISUAL snapshot coverage (OQ15 slice B).

The GPI radar (web/js/panels/player_gpi.js) gains a per-axis overlay: when the
/api/player-profile payload carries a "this_match" object (last game's per-axis
scores, keyed to the same 8 axes), a warn-tinted dot is drawn at each axis
vertex position for the last game's score, plus a one-line legend under the
caption ("last game - <champ> - <age> ago"). Axes whose this-match score is
null (versatility / consistency by contract) draw no dot. A payload without
this_match (or with this_match null) renders the shipped radar unchanged -
zero dots, no legend, no JS errors.

Mirrors the sibling test_player_gpi_view.py strategy: drive the real
showPlayerGpi against the live #player-gpi-panel mount with a stubbed
/api/player-profile payload, then assert the overlay geometry against the
module's own SVG constants (read from player_gpi.js: _CX=140, _CY=105, _R=66)
and screenshot the rendered panel.
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Shipped-style eight-axis payload plus a this_match block: match M999 on
# champion 64 played ~3h ago, six non-null axis scores (aggression 80.0 is the
# geometry anchor), versatility + consistency null per the frozen contract.
_GPI_MATCH_STUB = """
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
  const TM_AXES = [
    {key:'aggression',  score:80.0, value:1020.5},
    {key:'farming',     score:62.5, value:7.1},
    {key:'vision',      score:41.0, value:1.2},
    {key:'objectives',  score:55.0, value:3.0},
    {key:'survival',    score:33.3, value:6.0},
    {key:'tempo',       score:70.2, value:410.0},
    {key:'versatility', score:null, value:null},
    {key:'consistency', score:null, value:null}
  ];
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/player-profile') >= 0) {
      const body = {
        ok: true, mode: 'sr', champion: null,
        n_games: 619, window: 20, min_games: 10,
        confidence: 'high', axes: AXES, overall: 55.0,
        this_match: {
          match_id: 'M999',
          champion_id: 64,
          game_creation_ts: Date.now() - 3 * 3600 * 1000,
          axes: TM_AXES
        }
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

# Same shipped-style payload with NO this_match key at all - the shipped radar
# must render unchanged (zero dots, no legend, zero pageerrors).
_GPI_NO_MATCH_STUB = """
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


def _show_gpi(page):
    page.evaluate(
        """async () => {
          const m = await import('/js/panels/player_gpi.js');
          if (m._resetPlayerGpi) m._resetPlayerGpi();
          m.showPlayerGpi('sr', 'player-gpi-panel');
        }"""
    )
    page.wait_for_function(
        "document.querySelectorAll('#player-gpi-panel .gpi-area').length > 0",
        timeout=10_000,
    )


def test_match_dots_render_geometry_and_legend(mock_server, pw_browser):
    """Six non-null this-match axis scores -> exactly six overlay dots; the
    aggression dot (axis 0, score 80.0) sits at the hand-computed vertex; the
    legend line renders champ + age under the caption."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, _GPI_MATCH_STUB)
    _show_gpi(page)
    try:
        # (a) Exactly 6 dots - versatility + consistency are null -> skipped.
        dots = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-match-dot",
            "els => els.map(e => [e.getAttribute('cx'), e.getAttribute('cy')])",
        )
        assert len(dots) == 6, f"expected 6 match dots, got {len(dots)}: {dots}"

        # (b) Geometry anchor: aggression is axis 0 at twelve-o-clock. From the
        # module constants (_CX=140, _CY=105, _R=66) a score of 80.0 lands at
        # cx = _CX = 140 and cy = _CY - _R*0.8 = 105 - 52.8 = 52.2. The dots
        # are emitted in radar-axis order, so the aggression dot is first.
        cx, cy = dots[0]
        assert cx == "140", f"aggression dot cx expected 140, got {cx!r}"
        assert cy == "52.2", f"aggression dot cy expected 52.2, got {cy!r}"

        # (c) Legend under the caption: swatch + "last game - <champ>" + age.
        # The mock harness serves the real items_index.js, whose static CHAMPS
        # table resolves 64 -> "LeeSin"; assert either the resolved name or the
        # "cid:64" fallback so the test survives a name-table load race. The
        # ts is epoch-ms (> 1e12) so the relative-age suffix must render.
        legend = page.eval_on_selector(
            "#player-gpi-panel .gpi-match-legend", "el => el.textContent.trim()"
        )
        assert "last game" in legend, f"legend missing 'last game': {legend!r}"
        assert ("LeeSin" in legend) or ("64" in legend), (
            f"legend missing champ 64 name/fallback: {legend!r}"
        )
        assert "ago" in legend, f"legend missing relative age: {legend!r}"

        # (f) Visual artifact for the UI-audit ritual.
        SCREENSHOTS.mkdir(exist_ok=True)
        block = page.locator("#player-gpi-panel")
        block.screenshot(path=str(SCREENSHOTS / "player-gpi_match_dot.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_this_match_renders_shipped_radar(mock_server, pw_browser):
    """(d) Backward compat: payload without this_match -> the shipped radar
    renders (polygon present), zero dots, no legend, zero pageerrors."""
    ctx, page, errors = _open_champ_select(
        pw_browser, mock_server, _GPI_NO_MATCH_STUB
    )
    _show_gpi(page)
    try:
        n_area = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-area", "els => els.length"
        )
        assert n_area == 1, f"expected the shipped radar polygon, got {n_area}"
        n_dots = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-match-dot", "els => els.length"
        )
        assert n_dots == 0, f"expected zero match dots without this_match, got {n_dots}"
        n_legend = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-match-legend", "els => els.length"
        )
        assert n_legend == 0, f"expected no legend without this_match, got {n_legend}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_signature_includes_this_match(mock_server, pw_browser):
    """(e) Sig-dedup: two payloads differing only in this_match.match_id must
    produce different signatures (cache-staleness repaint), and a payload with
    this_match must differ from the same payload without it."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, _GPI_MATCH_STUB)
    try:
        sigs = page.evaluate(
            """async () => {
              const m = await import('/js/panels/player_gpi.js');
              const base = {
                ok: true, mode: 'sr', n_games: 10, window: 20, min_games: 10,
                confidence: 'high', overall: 50.0,
                axes: [{key: 'aggression', label: 'Aggression', score: 50.0}]
              };
              const tm = (mid) => ({
                match_id: mid, champion_id: 64, game_creation_ts: null,
                axes: [{key: 'aggression', score: 80.0, value: 900.0}]
              });
              const p1 = Object.assign({}, base, {this_match: tm('M111')});
              const p2 = Object.assign({}, base, {this_match: tm('M222')});
              const p3 = Object.assign({}, base);
              return [
                m.__test._signature(p1),
                m.__test._signature(p2),
                m.__test._signature(p3)
              ];
            }"""
        )
        assert sigs[0] != sigs[1], (
            f"signature must change with this_match.match_id: {sigs[0]!r}"
        )
        assert sigs[0] != sigs[2], (
            f"signature must differ with vs without this_match: {sigs!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """(g) Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
        Path(__file__).parents[2] / "web" / "js" / "panels" / "player_gpi.js",
        Path(__file__).parents[2] / "web" / "css" / "panels" / "player_gpi.css",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
