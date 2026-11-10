"""
tests/snapshot_panels/test_overlay_stats_brawl_no_benchmark.py
S144-U-274 (s144 uiux): the overlay stats mini-panel (w-stats,
web/js/panels/stats_panel.js) says "no benchmark" in a Brawl-routed game
(URF / ARURF / One for All / Nexus Blitz / GAMEMODEX all reach
state.mode "brawl", dashboard/view_router_state.py IN_GAME_MODES), instead of
comparing that game to a rank-tier SR average under a "Gold estimate" badge.

THE DEFECT. _benchMode() mapped every mode outside its table to "SR" (the
"overlay is SR-centric" default for an unset mode), and "brawl" was not in
the table. So a URF game (a Brawl game carries a live hp_max, the render
gate) fetched GET /api/rank-tier-bench?mode=SR and painted an average Gold
SR game's CS / KDA / KP beside it, badged "Gold estimate": the load-bearing
provenance badge vouched for a benchmark from a different game mode. The
rank-tier seed covers SR and ARAM only (core/rank_tier_bench.py
VALID_MODES).

THE FIX. "brawl" maps to its own BRAWL bench mode with the SR row set (LVL /
CS / KDA / KP, all with a live "You" value), and BRAWL joins ARENA as a mode
the seed does not cover: no route fetch, every Avg cell "-", the badge reads
"no benchmark". An unset mode still defaults to SR.

The route is fulfilled with the gold SR cell of the committed seed
(data/rank_tiers/rank_tier_averages.seed.json: cs 205, kda 2.5, kp 58) in
the route's documented body shape, so before the fix the Brawl render read
"Gold estimate" with 205 / 2.5 / 58 in the Avg column. Controls in the same
harness: the SR and unset-mode renders DO request the route and paint that
cell (so the fetch spy and the fulfilment are live), and Arena keeps its
"no benchmark" path.
"""
import json
from urllib.parse import parse_qs, urlparse

from tests.snapshot_panels.test_overlay_view import _open_overlay

_LC = {"hp_max": 1000, "level": 9, "cs": 61, "kda": "4/2/6",
       "game_time_s": 600, "kill_participation_pct": "55%"}

# Spies window.fetch, sets a benchmark rank tier, renders the REAL panel for
# `mode`, waits for any fetch to settle, then reads the rendered panel.
_RENDER = """
async ([lc, mode]) => {
  window.__benchCalls = [];
  const orig = window.fetch;
  window.fetch = (u, o) => {
    const s = String(u);
    if (s.indexOf('/api/rank-tier-bench') >= 0) window.__benchCalls.push(s);
    return orig(u, o);
  };
  localStorage.setItem('rc-pgr-rank-tier', 'gold');
  const m = await import('/js/panels/stats_panel.js');
  m._resetStatsPanel();
  const opts = mode === null ? undefined : { mode };
  if (mode === null) document.body.dataset.mode = '';
  m.renderStatsPanel(lc, opts);
  await new Promise(r => setTimeout(r, 600));
  const mount = document.getElementById('am-statspanel');
  const q = s => Array.from(mount.querySelectorAll(s)).map(e => e.textContent);
  return {
    hidden: mount.hidden,
    spMode: mount.dataset.spMode,
    src: (mount.querySelector('.sp-src') || {}).textContent,
    metrics: q('.sp-row .sp-metric'),
    you: q('.sp-row .sp-you'),
    bench: q('.sp-row .sp-bench-cell'),
    calls: window.__benchCalls,
  };
}
"""


# The gold SR seed cell, served for any mode the route is asked for.
_GOLD_SR = {"cs": {"avg": 205}, "kda": {"avg": 2.5}, "kp": {"avg": 58}}


def _fulfil_bench(route):
    qs = parse_qs(urlparse(route.request.url).query)
    body = {"ok": True, "tier": qs.get("tier", [""])[0],
            "mode": qs.get("mode", [""])[0],
            "bracket": qs.get("bracket", ["mid"])[0], "role": "all",
            "source": "static", "n": 3, "stats": _GOLD_SR,
            "cached": False, "elapsed_ms": 0}
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(body))


def _render(pw_browser, mock_server, mode):
    ctx, page, errors = _open_overlay(pw_browser, mock_server)
    try:
        page.route("**/api/rank-tier-bench*", _fulfil_bench)
        res = page.evaluate(_RENDER, [_LC, mode])
        return res, errors
    finally:
        ctx.close()


def test_brawl_game_says_no_benchmark_and_never_fetches_sr(mock_server, pw_browser):
    res, errors = _render(pw_browser, mock_server, "brawl")
    assert res["hidden"] is False, res
    assert res["spMode"] == "BRAWL", res
    assert res["src"] == "no benchmark", (
        f"a Brawl game is badged {res['src']!r}; the rank-tier seed has no "
        "Brawl benchmark, so it must read 'no benchmark'")
    assert res["calls"] == [], (
        f"a Brawl game requested a rank-tier benchmark: {res['calls']}")
    assert res["metrics"] == ["LVL", "CS", "KDA", "KP"], res
    assert res["you"] == ["9", "61", "5", "55"], res
    assert res["bench"] == ["-", "-", "-", "-"], res
    assert not errors, errors


def test_sr_game_still_requests_its_benchmark(mock_server, pw_browser):
    """Positive control: the spy sees the SR request, so an empty call list
    in the Brawl case is a real absence."""
    res, errors = _render(pw_browser, mock_server, "sr")
    assert res["spMode"] == "SR", res
    assert len(res["calls"]) == 1 and "mode=SR" in res["calls"][0], res
    assert res["src"] == "Gold estimate", res
    assert res["bench"] == ["-", "205", "2.5", "58"], res
    assert not errors, errors


def test_unset_mode_still_defaults_to_sr(mock_server, pw_browser):
    res, errors = _render(pw_browser, mock_server, None)
    assert res["spMode"] == "SR", res
    assert len(res["calls"]) == 1 and "mode=SR" in res["calls"][0], res
    assert not errors, errors


def test_arena_keeps_its_no_benchmark_path(mock_server, pw_browser):
    res, errors = _render(pw_browser, mock_server, "arena")
    assert res["spMode"] == "ARENA", res
    assert res["src"] == "no benchmark", res
    assert res["calls"] == [], res
    assert res["metrics"] == ["LVL", "KDA"], res
    assert not errors, errors
