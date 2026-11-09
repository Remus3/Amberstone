"""
tests/snapshot_panels/test_home_minimap_polls_need_rendered_panel.py
The Map State panel's two polls send nothing while the panel is not
rendered (session 144, lane uiux, S144-U-227).

The Map State panel (#minimap: the live minimap image, its caption, the
vision-tracker dots and the #mm-state line) sits in the top-level <main>.
Every view hides that <main> (web/css/panels/header.css, the
`body[data-view="..."] main { display: none; }` list, one line per
VIEW_ID by RM-1552), the page boots on data-view="home", applyView maps
any other id to "home", and the overlay shell hides `main > .panel`
(web/css/overlay.css). So the panel is never on screen. Its two polls in
web/js/main.js still ran during every SR / ARAM / Brawl game:
- refreshMinimap asked /api/minimap-crop (proxied to the supervisor, which
  crops the live frame) every 500 ms on the fast stream, 2 s otherwise;
- refreshVisionOverlay asked /api/vision-state every 500 ms.
MEASURED headless before the fix, on the Home view with an ARAM game live
and both feeds answering: 11 crop requests and 15 vision-state requests
in about 6.5 s of page clock, for a panel that was not rendered; and a crop
request open when the panel stopped rendering stayed open.

Both polls now return before sending while #minimap has no layout box
(getClientRects() is empty, i.e. it or an ancestor is display: none); the
crop poll also gives up on its open request then, so its answer never
paints. If a view ever renders the panel again, the polls resume on their
own at the next tick.

`show_coaching_main` (test_home_minimap_crop_poll_hung_feed.py) lets a
test render the panel: it adds one rule to the served index.html that
shows <main> in every view. The crop poll's hung-feed test uses it to keep
testing the poll mechanics.
Requests are counted in the page by the caller's stack, as in that test.

S144-U-256 retired the vision-tracker poll (refreshVisionOverlay and the
#mm-state line it fed), so /api/vision-state is now counted from ANY
caller here and pinned at zero on the Home view, rendered panel included
(test_minimap_state_line_retired.py pins the retired markup and names).
"""
import json

from tests.snapshot_panels.conftest import _ICON_STAND_IN, _WS_STUB
from tests.snapshot_panels.test_home_minimap_crop_poll_hung_feed import (
    _Crop,
    _Game,
    show_coaching_main,
)
from tests.snapshot_panels.test_ui_mock_active_match_map_stall import _vs

_COUNT_JS = r"""
(() => {
  const mk = () => ({ open: 0, max: 0, started: 0 });
  const s = { crop: mk(), vs: mk() };
  window.__mmPolls = s;
  const orig = window.fetch;
  window.fetch = function (input, opts) {
    const p = orig.apply(this, arguments);
    const url = String((input && input.url) || input);
    const stack = String(new Error().stack);
    let c = null;
    if (url.indexOf('/api/minimap-crop') >= 0
        && stack.indexOf('refreshMinimap') >= 0) c = s.crop;
    // S144-U-256: any caller; the Home view has no vision-state poll.
    if (url.indexOf('/api/vision-state') >= 0) c = s.vs;
    if (!c) return p;
    c.started += 1;
    c.open += 1;
    if (c.open > c.max) c.max = c.open;
    let closed = false;
    const close = () => { if (!closed) { closed = true; c.open -= 1; } };
    const sig = opts && opts.signal;
    if (sig) sig.addEventListener('abort', close);
    p.then(close, close);
    return p;
  };
})();
"""

_PANEL_JS = r"""
() => {
  const p = document.getElementById('minimap');
  const w = document.getElementById('mm-img-wrap');
  return {
    view: document.body.dataset.view,
    rendered: p.getClientRects().length > 0,
    hidden: w.classList.contains('hidden'),
    caption: document.getElementById('mm-img-caption').textContent,
    src: document.getElementById('mm-img').getAttribute('src') || '',
    polls: JSON.parse(JSON.stringify(window.__mmPolls)),
  };
}
"""


_LIVE_JS = """async () => {
  const { state } = await import('/js/lib/state.js');
  const lc = state.latest && state.latest.liveclient;
  return state.mode === 'aram' && !!lc && Object.keys(lc).length > 0;
}"""


def _vs_route(route):
    route.fulfill(status=200, content_type="application/json",
                  body=json.dumps(_vs(1_700_000_000.0)))


def _open(pw_browser, mock_server, crop, game, shown):
    mock_server.set_fixture("aram")
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_COUNT_JS)
    if shown:
        show_coaching_main(page)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/state-stream*", game.stream)
    page.route("**/api/state?*", game.poll)
    page.route("**/api/state", game.poll)
    page.route("**/api/minimap-crop*", crop)
    page.route("**/api/vision-state*", _vs_route)
    page.goto(mock_server.url + "/", wait_until="domcontentloaded",
              timeout=15_000)
    # The routed stream has landed the live game: the page state holds a
    # non-empty liveclient block and the ARAM mode (both poll gates open).
    page.wait_for_function(_LIVE_JS, timeout=10_000)
    return ctx, page, errors


def _advance(page, ms):
    """Run the page clock forward, then let the polls it fired land."""
    page.clock.run_for(ms)
    page.wait_for_timeout(400)
    page.clock.run_for(500)
    page.wait_for_timeout(400)
    return page.evaluate(_PANEL_JS)


def _close(page, ctx, mock_server):
    page.close()
    ctx.close()
    mock_server._store["data"] = {}


def test_no_view_and_no_shell_renders_the_map_state_panel(
    mock_server, pw_browser
):
    """The premise of the gate: #minimap has no layout box in any VIEW_ID
    or in the overlay shell. If a view starts rendering it, the polls
    resume there by themselves; update this pin and the main.js comment."""
    ctx, page, errors = _open(pw_browser, mock_server, _Crop("live"),
                              _Game(), shown=False)
    try:
        got = page.evaluate("""async () => {
          const { VIEW_IDS } = await import('/js/lib/state.js');
          const p = document.getElementById('minimap');
          const b = document.body;
          const keep = b.dataset.view;
          const out = {};
          for (const v of VIEW_IDS) {
            b.dataset.view = v;
            out[v] = p.getClientRects().length;
          }
          b.dataset.view = keep;
          b.dataset.shell = 'overlay';
          out.overlay_shell = p.getClientRects().length;
          delete b.dataset.shell;
          return out;
        }""")
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert len(got) >= 13, got  # 12 views + the overlay shell
    assert all(n == 0 for n in got.values()), got


def test_a_hidden_panel_sends_neither_poll(mock_server, pw_browser):
    crop = _Crop("live")
    ctx, page, errors = _open(pw_browser, mock_server, crop, _Game(),
                              shown=False)
    try:
        got = _advance(page, 6_000)
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert got["view"] == "home", got
    assert not got["rendered"], got
    assert got["polls"]["crop"]["started"] == 0, got["polls"]
    assert got["polls"]["vs"]["started"] == 0, got["polls"]
    assert crop.hits == 0, crop.hits


def test_a_rendered_panel_polls_and_paints(mock_server, pw_browser):
    """Positive control: the same live game with the panel rendered sends
    the crop poll (one request open at a time) and paints the image; the
    retired vision-tracker poll sends nothing even then (S144-U-256)."""
    crop = _Crop("live")
    ctx, page, errors = _open(pw_browser, mock_server, crop, _Game(),
                              shown=True)
    try:
        got = _advance(page, 6_000)
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert got["rendered"], got
    assert got["polls"]["crop"]["started"] >= 8, got["polls"]
    assert got["polls"]["crop"]["max"] == 1, got["polls"]
    assert got["polls"]["vs"]["started"] == 0, got["polls"]
    assert not got["hidden"] and got["caption"].startswith("ARAM"), got
    assert got["src"].startswith("blob:"), got


def test_hiding_the_panel_drops_the_open_crop_request(
    mock_server, pw_browser
):
    """A crop request open when the panel stops rendering is given up on,
    no new one is sent (nor a vision-state one), and its late answer never
    paints."""
    crop = _Crop("hung")
    ctx, page, errors = _open(pw_browser, mock_server, crop, _Game(),
                              shown=True)
    try:
        got = _advance(page, 1_000)
        assert got["polls"]["crop"]["open"] == 1, got["polls"]
        assert got["src"] == "", got
        page.evaluate(
            "() => document.getElementById('test-show-main').remove()")
        got = _advance(page, 1_000)
        assert not got["rendered"], got
        assert got["polls"]["crop"]["open"] == 0, got["polls"]
        sent = got["polls"]["crop"]["started"]
        vs_sent = got["polls"]["vs"]["started"]
        for r in crop.held:
            try:
                r.fulfill(status=200, content_type="image/jpeg",
                          body=_ICON_STAND_IN)
            except Exception:  # noqa: BLE001 - aborted, cannot be answered
                pass
        got = _advance(page, 6_000)
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert got["polls"]["crop"]["started"] == sent, got["polls"]
    # No vision-state request at any point (S144-U-256 retired that poll).
    assert vs_sent == 0, got["polls"]
    assert got["polls"]["vs"]["started"] == 0, got["polls"]
    assert got["src"] == "", got
    assert got["hidden"], got
