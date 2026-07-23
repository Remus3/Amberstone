"""
tests/snapshot_panels/test_player_gpi_reference_view.py
Player-GPI target-profile REFERENCE polygon VISUAL snapshot coverage.

The GPI radar (web/js/panels/player_gpi.js) gains a second polygon: when the
/api/player-profile payload carries a "reference" object (the same 8 axes
scored over the operator's OWN winning games), a dashed teal ring is drawn
BEHIND the recent-form polygon, plus a one-line legend under the caption
("reference - winning games (N)"). A payload without reference (or with
reference null) renders the shipped radar unchanged - no ring, no legend, no
JS errors.

Mirrors the sibling test_player_gpi_match_dot_view.py strategy: drive the real
showPlayerGpi against the live #player-gpi-panel mount with a stubbed
/api/player-profile payload, then assert the polygon geometry + paint order
against the module's own SVG constants (_CX=140, _CY=105, _R=66) and
screenshot the rendered panel.
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

_AXES_JS = """
  const AXES = [
    {key:'aggression',  label:'Aggression',  unit:'dmg/min', scoring:'relative', higher_is_better:true,  score:50.1, recent_value:861.04, baseline_p50:819.32, sample_n:20},
    {key:'farming',     label:'Farming',     unit:'cs/min',  scoring:'relative', higher_is_better:true,  score:51.9, recent_value:7.4,    baseline_p50:6.8,    sample_n:20},
    {key:'vision',      label:'Vision',      unit:'vis/min', scoring:'relative', higher_is_better:true,  score:60.1, recent_value:1.1,    baseline_p50:1.3,    sample_n:20},
    {key:'objectives',  label:'Objectives',  unit:'obj/game', scoring:'relative', higher_is_better:true, score:41.5, recent_value:3.2,    baseline_p50:2.6,    sample_n:20},
    {key:'survival',    label:'Survival',    unit:'deaths/min', scoring:'relative', higher_is_better:false, score:30.0, recent_value:5.1, baseline_p50:5.0,  sample_n:20},
    {key:'tempo',       label:'Tempo',       unit:'gold/min', scoring:'relative', higher_is_better:true, score:48.1, recent_value:402.0,  baseline_p50:388.0,  sample_n:20},
    {key:'versatility', label:'Versatility', unit:'champ pool', scoring:'absolute', higher_is_better:true, score:44.9, recent_value:4,   baseline_p50:null,   sample_n:20},
    {key:'consistency', label:'Consistency', unit:'KDA cv',  scoring:'absolute', higher_is_better:true,  score:37.0, recent_value:0.9,    baseline_p50:null,   sample_n:20}
  ];
"""

# Reference scores mirror the live SR probe (2026-07-23): the winning-games
# polygon sits outside the recent-form polygon on objectives / survival /
# tempo. aggression 55.0 is the geometry anchor (axis 0, twelve-o-clock).
_REF_JS = """
  const REF = {
    kind: 'own_wins', label: 'winning games', n: 20, min_games: 5,
    axes: [
      {key:'aggression',  score:55.0},
      {key:'farming',     score:56.2},
      {key:'vision',      score:67.1},
      {key:'objectives',  score:65.5},
      {key:'survival',    score:45.2},
      {key:'tempo',       score:63.1},
      {key:'versatility', score:44.3},
      {key:'consistency', score:49.6}
    ]
  };
"""


def _stub(body_extra: str, ref_js: str = "") -> str:
    return ("""
(function () {
  const _f = window.fetch;
""" + _AXES_JS + ref_js + """
  window.fetch = function (u, o) {
    const url = (typeof u === 'string') ? u : (u && u.url) || '';
    if (url.indexOf('/api/player-profile') >= 0) {
      const body = {
        ok: true, mode: 'sr', champion: null,
        n_games: 634, window: 20, min_games: 10,
        confidence: 'high', axes: AXES, overall: 45.4""" + body_extra + """
      };
      return Promise.resolve(new Response(
        JSON.stringify(body),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      ));
    }
    return _f.apply(this, arguments);
  };
})();
""")


_GPI_REF_STUB = _stub(", reference: REF", _REF_JS)
_GPI_NO_REF_STUB = _stub("")
_GPI_NULL_REF_STUB = _stub(", reference: null")
# A malformed reference (one axis missing a score) must draw NOTHING rather
# than a partial ring that reads as a real shape.
_GPI_PARTIAL_REF_STUB = _stub(
    ", reference: {kind:'own_wins', label:'winning games', n:20,"
    " axes: REF.axes.map((a, i) => i === 3 ? {key: a.key, score: null} : a)}",
    _REF_JS,
)


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
    page.goto(
        mock_server.url + "/?ui_mock=1&mode=sr#champ-select",
        wait_until="domcontentloaded", timeout=15_000,
    )
    return ctx, page, errors


def _show_gpi(page):
    page.evaluate(
        """async () => {
          let mount = document.getElementById('player-gpi-panel');
          if (!mount) {
            mount = document.createElement('section');
            mount.id = 'player-gpi-panel';
            mount.className = 'player-gpi';
            mount.hidden = true;
            const host = document.querySelector(
              '#view-champ-select .csv-card-suggestions .csv-card-body')
              || document.body;
            host.appendChild(mount);
          }
          const m = await import('/js/panels/player_gpi.js');
          if (m._resetPlayerGpi) m._resetPlayerGpi();
          m.showPlayerGpi('sr', 'player-gpi-panel');
        }"""
    )
    page.wait_for_function(
        "document.querySelectorAll('#player-gpi-panel .gpi-area').length > 0",
        timeout=10_000,
    )


def test_reference_polygon_geometry_and_legend(mock_server, pw_browser):
    """(a) Exactly one reference ring with eight vertices, (b) the aggression
    vertex sits at the hand-computed position, (c) the legend renders."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, _GPI_REF_STUB)
    _show_gpi(page)
    try:
        pts = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-ref-area",
            "els => els.map(e => e.getAttribute('points'))",
        )
        assert len(pts) == 1, f"expected one reference polygon, got {len(pts)}"
        verts = pts[0].split(" ")
        assert len(verts) == 8, f"expected 8 reference vertices, got {verts}"

        # Geometry anchor: aggression is axis 0 at twelve-o-clock. From the
        # module constants (_CX=140, _CY=105, _R=66) a reference score of 55.0
        # lands at x = 140 and y = 105 - 66*0.55 = 105 - 36.3 = 68.7.
        assert verts[0] == "140,68.7", (
            f"aggression reference vertex expected 140,68.7, got {verts[0]!r}"
        )

        legend = page.eval_on_selector(
            "#player-gpi-panel .gpi-ref-legend", "el => el.textContent.trim()"
        )
        assert "reference" in legend, f"legend missing 'reference': {legend!r}"
        assert "winning games" in legend, f"legend missing label: {legend!r}"
        assert "(20)" in legend, f"legend missing win count: {legend!r}"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#player-gpi-panel").screenshot(
            path=str(SCREENSHOTS / "player-gpi_reference.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_reference_paints_behind_the_player_polygon(mock_server, pw_browser):
    """The reference ring must precede .gpi-area in document order so the
    filled recent-form polygon paints ON TOP of it (SVG has no z-index)."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, _GPI_REF_STUB)
    _show_gpi(page)
    try:
        order = page.evaluate(
            """() => {
              const svg = document.querySelector('#player-gpi-panel .gpi-radar');
              const kids = Array.from(svg.children);
              return [
                kids.findIndex(e => e.classList.contains('gpi-ref-area')),
                kids.findIndex(e => e.classList.contains('gpi-area'))
              ];
            }"""
        )
        assert order[0] >= 0, "reference polygon not found in the radar svg"
        assert order[0] < order[1], (
            f"reference must paint behind the data polygon, got indices {order}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_missing_or_null_reference_renders_shipped_radar(mock_server, pw_browser):
    """(d) Backward compat: no reference key, and reference null, both render
    the shipped radar - polygon present, zero rings, no legend, no errors."""
    for stub in (_GPI_NO_REF_STUB, _GPI_NULL_REF_STUB):
        ctx, page, errors = _open_champ_select(pw_browser, mock_server, stub)
        _show_gpi(page)
        try:
            n_area = page.eval_on_selector_all(
                "#player-gpi-panel .gpi-area", "els => els.length"
            )
            assert n_area == 1, f"expected the shipped radar polygon, got {n_area}"
            n_ref = page.eval_on_selector_all(
                "#player-gpi-panel .gpi-ref-area", "els => els.length"
            )
            assert n_ref == 0, f"expected zero reference rings, got {n_ref}"
            n_legend = page.eval_on_selector_all(
                "#player-gpi-panel .gpi-ref-legend", "els => els.length"
            )
            assert n_legend == 0, f"expected no reference legend, got {n_legend}"
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors: {errors[:3]}"


def test_partial_reference_draws_no_ring(mock_server, pw_browser):
    """A reference block with a null axis score is all-or-nothing: no ring at
    all rather than a silently-truncated shape."""
    ctx, page, errors = _open_champ_select(
        pw_browser, mock_server, _GPI_PARTIAL_REF_STUB
    )
    _show_gpi(page)
    try:
        n_ref = page.eval_on_selector_all(
            "#player-gpi-panel .gpi-ref-area", "els => els.length"
        )
        assert n_ref == 0, f"partial reference must draw no ring, got {n_ref}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_signature_includes_reference(mock_server, pw_browser):
    """Sig-dedup: two payloads differing only in a reference axis score must
    produce different signatures, and with-vs-without must differ."""
    ctx, page, errors = _open_champ_select(pw_browser, mock_server, _GPI_REF_STUB)
    try:
        sigs = page.evaluate(
            """async () => {
              const m = await import('/js/panels/player_gpi.js');
              const base = {
                ok: true, mode: 'sr', n_games: 10, window: 20, min_games: 10,
                confidence: 'high', overall: 50.0,
                axes: [{key: 'aggression', label: 'Aggression', score: 50.0}]
              };
              const ref = (s) => ({
                kind: 'own_wins', label: 'winning games', n: 20,
                axes: [{key: 'aggression', score: s}]
              });
              return [
                m.__test._signature(Object.assign({}, base, {reference: ref(55.0)})),
                m.__test._signature(Object.assign({}, base, {reference: ref(66.0)})),
                m.__test._signature(Object.assign({}, base))
              ];
            }"""
        )
        assert sigs[0] != sigs[1], (
            f"signature must change with a reference score: {sigs[0]!r}"
        )
        assert sigs[0] != sigs[2], (
            f"signature must differ with vs without reference: {sigs!r}"
        )
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
        Path(__file__).parents[2] / "core" / "player_gpi.py",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
