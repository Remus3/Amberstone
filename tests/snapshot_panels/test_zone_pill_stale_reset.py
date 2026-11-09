"""
tests/snapshot_panels/test_zone_pill_stale_reset.py
S144-U-244 (s144 uiux): when the Active Match minimap loses your position,
the header zone pill goes back to its "-" placeholder and the body loses
its zone tint, instead of keeping the last zone call.

THE DEFECTS. MEASURED headless under /?ui_mock=1&mode=sr#active-match by
driving web/js/panels/map_state.js renderMinimapCanvases() with a value
shape that puts you deep in enemy pressure (three enemies stacked on your
dot), then with one that drops your position:
- your champion dead (ally_respawns > 0) or missing from the ally
  positions: the pill gained .hidden but kept className "zone-pill
  zone-enemy zone-deep" and the label "DEEP ENEMY", so the static-pill
  rule (header.css) showed the stale call, greyed, in the header slot and
  to the aria-live region;
- no positions at all (vision lost the minimap): the early return left
  the pill fully lit and pulsing with "DEEP ENEMY", and left
  body[data-zone="deep"], which keeps the red tint on the right-now panel
  and the minimap stack (map_state.css).

THE FIX. One reset (map_state.js _clearZone) on both no-position paths:
className "zone-pill hidden", label "-", body[data-zone] removed.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_DRIVE = """async () => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/map_state.js'));
  if (!url) return {err: 'map_state.js not loaded'};
  const m = await import(url);
  const zp = document.getElementById('zone-pill');
  const zl = document.getElementById('zone-label');
  const read = () => ({cls: String(zp.className), label: zl.textContent,
                       zone: document.body.dataset.zone ?? null,
                       shown: zp.checkVisibility()});
  const deep = {
    champion: 'Ahri', my_team: 'blue', game_time_s: 900,
    positions: {
      allies: {Ahri: {x: 0.80, y: 0.20}},
      enemies: {Zed: {x: 0.80, y: 0.20}, Lux: {x: 0.80, y: 0.21},
                Jinx: {x: 0.81, y: 0.20}},
    },
  };
  const lost = {
    dead: {...deep, ally_respawns: {Ahri: 12}},
    absent: {...deep, champion: 'Garen'},
    nopos: {champion: 'Ahri', my_team: 'blue', game_time_s: 900,
            positions: null},
    empty: {...deep, positions: {allies: {}, enemies: {}}},
  };
  const out = {};
  for (const [k, p] of Object.entries(lost)) {
    m.renderMinimapCanvases(deep);
    const before = read();
    m.renderMinimapCanvases(p);
    out[k] = {before, after: read()};
  }
  return out;
}"""

_CASES = ["dead", "absent", "nopos", "empty"]


@pytest.fixture(scope="module")
def driven(mock_server, pw_browser):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1&mode=sr#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        got = page.evaluate(_DRIVE)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    return got


@pytest.mark.parametrize("case", _CASES)
def test_the_deep_call_is_live_before_the_position_drops(driven, case):
    # Anchor: the payload really reaches the deep-enemy branch, so the
    # reset assertions below are not passing on a pill that never lit.
    b = driven[case]["before"]
    assert "zone-deep" in b["cls"].split(), b
    assert "DEEP ENEMY" in b["label"], b
    assert b["zone"] == "deep", b
    assert b["shown"], b


@pytest.mark.parametrize("case", _CASES)
def test_a_lost_position_resets_the_pill_to_its_placeholder(driven, case):
    a = driven[case]["after"]
    assert a["cls"] == "zone-pill hidden", a
    assert a["label"] == "-", a


@pytest.mark.parametrize("case", _CASES)
def test_a_lost_position_clears_the_body_zone_tint(driven, case):
    a = driven[case]["after"]
    assert a["zone"] is None, a


@pytest.mark.parametrize("case", _CASES)
def test_the_placeholder_keeps_its_header_slot(driven, case):
    # Static-pill rule: the reset pill stays in the header row as "-".
    assert driven[case]["after"]["shown"], driven[case]["after"]
