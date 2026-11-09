"""
tests/snapshot_panels/test_minimap_hidden_canvas_paint.py
S144-U-246 (s144 uiux): the Map State panel's two 720x720 canvases
(#mm-zoi-canvas, #mm-pos-canvas) are painted only while they have a
layout box, and the header zone pill keeps working when they do not.

THE DEFECT. MEASURED headless under /?ui_mock=1&mode=sr#active-match.
The #minimap panel sits in the top-level <main>, which header.css hides
for every VIEW_ID and overlay.css hides in the overlay shell, so its
canvas stack never renders (S144-U-227 measured the same for its two
polls). web/js/panels/map_state.js renderMinimapCanvases() still ran the
whole paint every state tick: the 720x720 ZOI field (_drawZoi, its
per-pixel offscreen math then drawImage), the objective glyphs, every
champion dot and the ghost rings, into canvases nobody can see. Its only
skip was document.hidden. The one live output of that function is the
header zone pill (netAtSelf), which was computed in the middle of the
paint.

THE FIX. renderMinimapCanvases computes the zone pill first, then paints
only when #mm-canvas-stack has a layout box (getClientRects), the same
gate the panel's polls use. A view that renders the panel again gets the
paint back on its next tick, with no other change.

The positive control forces the panel on screen and requires the paint
to run, so the zero-paint assertion cannot pass on a broken counter.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_DRIVE = """async (forceShown) => {
  const url = performance.getEntriesByType('resource')
    .map((e) => e.name).find((n) => n.includes('/panels/map_state.js'));
  if (!url) return {err: 'map_state.js not loaded'};
  const m = await import(url);
  if (forceShown) {
    const st = document.createElement('style');
    st.textContent = 'body main, #minimap { display: block !important; }';
    document.head.appendChild(st);
  }
  const ids = new Set(['mm-zoi-canvas', 'mm-pos-canvas']);
  const counts = {};
  const bump = (k) => { counts[k] = (counts[k] || 0) + 1; };
  const P = CanvasRenderingContext2D.prototype;
  const fns = ['putImageData', 'drawImage', 'arc', 'fillText',
               'clearRect', 'fill', 'stroke', 'fillRect'];
  const saved = {};
  for (const fn of fns) {
    saved[fn] = P[fn];
    P[fn] = function (...a) {
      if (this.canvas && ids.has(this.canvas.id)) bump(fn);
      return saved[fn].apply(this, a);
    };
  }
  const C = HTMLCanvasElement.prototype;
  const savedGet = C.getContext;
  C.getContext = function (...a) {
    if (ids.has(this.id)) bump('getContext');
    return savedGet.apply(this, a);
  };
  const deep = {
    champion: 'Ahri', my_team: 'blue', game_time_s: 900, mode: 'sr',
    positions: {
      allies: {Ahri: {x: 0.80, y: 0.20}, Garen: {x: 0.20, y: 0.80}},
      enemies: {Zed: {x: 0.80, y: 0.20}, Lux: {x: 0.80, y: 0.21},
                Jinx: {x: 0.81, y: 0.20}},
    },
  };
  let threw = null;
  try {
    m.renderMinimapCanvases(deep);
  } catch (e) {
    threw = String(e);
  } finally {
    for (const fn of fns) P[fn] = saved[fn];
    C.getContext = savedGet;
  }
  const stack = document.getElementById('mm-canvas-stack');
  const zp = document.getElementById('zone-pill');
  const zl = document.getElementById('zone-label');
  return {
    threw, counts,
    total: Object.values(counts).reduce((a, b) => a + b, 0),
    stackBoxes: stack.getClientRects().length,
    stackHiddenClass: stack.classList.contains('hidden'),
    pill: String(zp.className), label: zl.textContent,
    zone: document.body.dataset.zone ?? null,
    myteam: document.body.dataset.myteam ?? null,
  };
}"""


def _drive(mock_server, pw_browser, force_shown):
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
        got = page.evaluate(_DRIVE, force_shown)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert "err" not in got, got
    assert got["threw"] is None, got
    return got


@pytest.fixture(scope="module")
def hidden(mock_server, pw_browser):
    return _drive(mock_server, pw_browser, False)


@pytest.fixture(scope="module")
def shown(mock_server, pw_browser):
    return _drive(mock_server, pw_browser, True)


def test_the_canvas_stack_has_no_layout_box_in_active_match(hidden):
    # Anchor: the stack is un-hidden by its own class (positions exist),
    # yet has no box, because its <main> ancestor is display:none.
    assert hidden["stackHiddenClass"] is False, hidden
    assert hidden["stackBoxes"] == 0, hidden


def test_a_stack_without_a_box_is_not_painted(hidden):
    assert hidden["total"] == 0, hidden["counts"]


def test_the_zone_pill_still_reads_deep_enemy_without_the_paint(hidden):
    assert "zone-deep" in hidden["pill"].split(), hidden
    assert "DEEP ENEMY" in hidden["label"], hidden
    assert hidden["zone"] == "deep", hidden
    assert hidden["myteam"] == "blue", hidden


def test_positive_control_the_forced_on_panel_has_a_box(shown):
    assert shown["stackBoxes"] > 0, shown


def test_positive_control_a_rendered_stack_is_painted(shown):
    c = shown["counts"]
    # The ZOI field lands on its canvas, and the dots on theirs.
    assert c.get("drawImage", 0) + c.get("putImageData", 0) >= 1, c
    assert c.get("arc", 0) >= 5, c
    assert c.get("fillText", 0) >= 1, c


def test_positive_control_the_zone_pill_matches_the_hidden_case(shown, hidden):
    for k in ("pill", "label", "zone", "myteam"):
        assert shown[k] == hidden[k], (k, shown[k], hidden[k])
