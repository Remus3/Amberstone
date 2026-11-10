"""
tests/snapshot_panels/test_home_minimap_polls_need_rendered_panel.py
The Map State panel (#minimap) is rendered in no view, and the page sends
no Map State poll, rendered panel or not (session 144, lane uiux,
S144-U-227; narrowed by S144-U-256 and S144-U-257).

The Map State panel sits in the top-level <main>. Every view hides that
<main> (web/css/panels/header.css, the `body[data-view="..."] main
{ display: none; }` list, one line per VIEW_ID by RM-1552), the page boots
on data-view="home", applyView maps any other id to "home", and the
overlay shell hides `main > .panel` (web/css/overlay.css). So the panel is
never on screen. It used to carry two polls in web/js/main.js that still
ran during every SR / ARAM / Brawl game:
- the live crop image poll asked /api/minimap-crop every 500 ms on the
  fast stream, 2 s otherwise;
- the vision-tracker poll asked /api/vision-state every 500 ms.
MEASURED headless before S144-U-227, on the Home view with an ARAM game
live and both feeds answering: 11 crop requests and 15 vision-state
requests in about 6.5 s of page clock, for a panel that was not rendered.

S144-U-227 gated both on the panel having a layout box. S144-U-256
retired the vision-tracker poll and S144-U-257 the crop image poll, with
the markup they fed (pinned by test_minimap_state_line_retired.py and
test_minimap_crop_image_retired.py). So this module now pins:
- the premise: no VIEW_ID and not the overlay shell renders #minimap;
- with a live ARAM game up, neither route is fetched from the Home view,
  whether the panel is hidden (every real view) or forced to render by
  `show_coaching_main` (one test rule that shows <main> in every view);
- a positive control: the counter does count a fetch of either route, so
  a zero above is not a blind counter.
Requests are counted in the page from ANY caller by wrapping window.fetch.

S144-U-264 retired the #minimap shell itself
(test_minimap_panel_shell_retired.py). The premise now reads the panel's
parent: no node is served, the top-level <main> has no layout box in any
VIEW_ID, and in the overlay shell it only wraps the #right-now widget
mounts; "rendered" below means that <main> has a box (forced by
show_coaching_main).
"""
import json

from tests.snapshot_panels._route_match import on_path
from tests.snapshot_panels.conftest import _ICON_STAND_IN, _WS_STUB, FIXTURE_DIR
from tests.snapshot_panels.test_ui_mock_active_match_map_stall import _vs

_SHOW_MAIN_CSS = (
    '<style id="test-show-main">body[data-view] main'
    " { display: grid !important; }</style>"
)


def show_coaching_main(page):
    """Serve index.html with one extra rule that renders the top-level
    <main> (and so the Map State panel) in every view. Call before goto."""

    def handler(route):
        resp = route.fetch()
        body = resp.text().replace("</head>", _SHOW_MAIN_CSS + "</head>", 1)
        route.fulfill(response=resp, body=body)

    # Compiled path matchers, not a Python callable (RM-1506 guard).
    page.route(on_path("/"), handler)
    page.route(on_path("/index.html"), handler)


# Synthetic derived-shape block (dashboard/_liveclient summary keys); no
# real game id, match id, puuid or Riot ID (RM-906).
_LIVECLIENT = {
    "game_mode": "ARAM", "source": "live_api", "game_time_s": 312.0,
    "level": 9, "cs": 41, "kda": "3/2/7",
}


class _Game:
    """The live ARAM game the page sees, over /api/state-stream and
    /api/state."""

    def __init__(self):
        self.base = json.loads(
            (FIXTURE_DIR / "aram.json").read_text("utf-8"))

    def payload(self):
        d = dict(self.base)
        d["liveclient"] = dict(_LIVECLIENT)
        return json.dumps(d)

    def stream(self, route):
        route.fulfill(status=200, content_type="text/event-stream",
                      body="retry: 150\n\ndata: " + self.payload() + "\n\n")

    def poll(self, route):
        route.fulfill(status=200, content_type="application/json",
                      body=self.payload())


class _Hits:
    """Route stand-in that answers and counts what reached the network."""

    def __init__(self, content_type, body):
        self.content_type = content_type
        self.body = body
        self.hits = 0

    def __call__(self, route):
        self.hits += 1
        route.fulfill(status=200, content_type=self.content_type,
                      body=self.body)


_COUNT_JS = r"""
(() => {
  const s = { crop: 0, vs: 0 };
  window.__mmPolls = s;
  const orig = window.fetch;
  window.fetch = function (input) {
    const url = String((input && input.url) || input);
    if (url.indexOf('/api/minimap-crop') >= 0) s.crop += 1;
    if (url.indexOf('/api/vision-state') >= 0) s.vs += 1;
    return orig.apply(this, arguments);
  };
})();
"""

_PANEL_JS = r"""
() => ({
  view: document.body.dataset.view,
  panel: !!document.getElementById('minimap'),
  rendered: document.querySelector('body > main').getClientRects().length > 0,
  polls: Object.assign({}, window.__mmPolls),
})
"""

_LIVE_JS = """async () => {
  const { state } = await import('/js/lib/state.js');
  const lc = state.latest && state.latest.liveclient;
  return state.mode === 'aram' && !!lc && Object.keys(lc).length > 0;
}"""


def _open(pw_browser, mock_server, shown):
    mock_server.set_fixture("aram")
    game = _Game()
    crop = _Hits("image/jpeg", _ICON_STAND_IN)
    vs = _Hits("application/json", json.dumps(_vs(1_700_000_000.0)))
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
    page.route("**/api/vision-state*", vs)
    page.goto(mock_server.url + "/", wait_until="domcontentloaded",
              timeout=15_000)
    # The routed stream has landed the live game: the page state holds a
    # non-empty liveclient block and the ARAM mode (the gates the retired
    # polls waited on are open).
    page.wait_for_function(_LIVE_JS, timeout=10_000)
    return ctx, page, errors, crop, vs


def _advance(page, ms):
    """Run the page clock forward, then let anything it fired land."""
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
    """The premise: #minimap is not served (S144-U-264), the <main> it
    sat in has no layout box in any VIEW_ID, and in the overlay shell
    <main> is only the wrapper for the #right-now widget mounts (no other
    panel in it has a box). If a view starts rendering <main>, re-decide
    what it shows; update this pin."""
    ctx, page, errors, _crop, _vs_hits = _open(pw_browser, mock_server,
                                               shown=False)
    try:
        got = page.evaluate("""async () => {
          const { VIEW_IDS } = await import('/js/lib/state.js');
          const p = document.querySelector('body > main');
          const b = document.body;
          const keep = b.dataset.view;
          const out = {views: {}};
          out.panelNode = !!document.getElementById('minimap');
          for (const v of VIEW_IDS) {
            b.dataset.view = v;
            out.views[v] = p.getClientRects().length;
          }
          b.dataset.view = keep;
          b.dataset.shell = 'overlay';
          out.overlayPanels = Array.from(p.children)
            .filter((e) => e.getClientRects().length > 0)
            .map((e) => e.id);
          delete b.dataset.shell;
          return out;
        }""")
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert got["panelNode"] is False, got
    assert len(got["views"]) >= 12, got
    rendered = {k: n for k, n in got["views"].items() if n}
    assert rendered == {}, rendered
    assert got["overlayPanels"] == ["right-now"], got


def test_a_hidden_panel_sends_neither_poll(mock_server, pw_browser):
    ctx, page, errors, crop, vs = _open(pw_browser, mock_server,
                                        shown=False)
    try:
        got = _advance(page, 6_000)
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert got["view"] == "home", got
    assert not got["rendered"], got
    assert got["polls"] == {"crop": 0, "vs": 0}, got
    assert crop.hits == 0 and vs.hits == 0, (crop.hits, vs.hits)


def test_a_rendered_panel_sends_neither_poll_either(mock_server, pw_browser):
    """Before S144-U-257 this was the positive control: the rendered panel
    sent the crop poll (8+ requests in 6.5 s) and painted the image. Both
    polls are retired now, so a rendered panel sends nothing too."""
    ctx, page, errors, crop, vs = _open(pw_browser, mock_server, shown=True)
    try:
        got = _advance(page, 6_000)
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert got["rendered"] and got["panel"] is False, got
    assert got["polls"] == {"crop": 0, "vs": 0}, got
    assert crop.hits == 0 and vs.hits == 0, (crop.hits, vs.hits)


def test_positive_control_the_counter_sees_both_routes(
    mock_server, pw_browser
):
    """The zeros above are not a blind counter: a fetch of each route from
    the page is counted in the page and reaches its route stand-in."""
    ctx, page, errors, crop, vs = _open(pw_browser, mock_server, shown=True)
    try:
        page.evaluate("""async () => {
          await fetch('/api/minimap-crop?mode=aram');
          await fetch('/api/vision-state');
        }""")
        got = page.evaluate(_PANEL_JS)
    finally:
        _close(page, ctx, mock_server)
    assert not errors, errors[:3]
    assert got["polls"] == {"crop": 1, "vs": 1}, got
    assert crop.hits == 1 and vs.hits == 1, (crop.hits, vs.hits)
