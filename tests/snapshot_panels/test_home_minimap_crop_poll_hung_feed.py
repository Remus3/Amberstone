"""
tests/snapshot_panels/test_home_minimap_crop_poll_hung_feed.py
The Home minimap's /api/minimap-crop poll when the server stops ANSWERING
(session 144, lane uiux, S144-U-226; the sibling of S144-U-225).

web/js/main.js refreshMinimap fetches the live minimap image every 500 ms
(a JPEG answer, the fast stream) or 2 s (a PNG answer, the re-crop) while a
game is up in SR / ARAM / Brawl. It sent a new fetch each tick with no
timeout and no limit on how many were open, so
- every tick of a server that stopped answering added one more open
  request, and the image never said it had gone stale (no request ever
  failed, so the catch that marks it STALE never ran);
- a request still open when the game ended could land afterwards and show
  the minimap again over the hidden, game-over state.

The poll now keeps at most one request open: a tick that finds one still
open sends nothing; a request still unanswered after
MINIMAP_FETCH_TIMEOUT_MS (5 s) is aborted and settles as a failure (the
image is marked STALE), so the next tick asks again; leaving the game (or
the minimap modes) gives up on the open request, so its answer never paints;
a mode change (SR to ARAM) gives up on a request sent for the old map; an
answer for a request given up on never paints.

The open-request count is measured in the page: an init script wraps
window.fetch and counts the /api/minimap-crop requests sent from
refreshMinimap (by the caller's stack) until each settles or its signal
aborts. Time moves with Playwright's clock. The game state reaches the page
through a routed /api/state-stream (and /api/state, the fallback poll), so a
test can end the game mid-run. Drive path: / with the ARAM fixture plus a
small synthetic derived liveclient block (refreshMinimap only asks that it
is non-empty).
"""
import json
from urllib.parse import parse_qs, urlparse

from tests.snapshot_panels.conftest import _ICON_STAND_IN, _WS_STUB, FIXTURE_DIR

_COUNT_JS = r"""
(() => {
  const s = { open: 0, max: 0, started: 0 };
  window.__hmMc = s;
  const orig = window.fetch;
  window.fetch = function (input, opts) {
    const p = orig.apply(this, arguments);
    const url = String((input && input.url) || input);
    if (url.indexOf('/api/minimap-crop') < 0) return p;
    if (String(new Error().stack).indexOf('refreshMinimap') < 0) return p;
    s.started += 1;
    s.open += 1;
    if (s.open > s.max) s.max = s.open;
    let closed = false;
    const close = () => { if (!closed) { closed = true; s.open -= 1; } };
    const sig = opts && opts.signal;
    if (sig) sig.addEventListener('abort', close);
    p.then(close, close);
    return p;
  };
})();
"""

_WRAP_JS = r"""
() => {
  const w = document.getElementById('mm-img-wrap');
  const c = document.getElementById('mm-img-caption');
  return {
    hidden: w.classList.contains('hidden'),
    stale: w.classList.contains('stale'),
    caption: c ? c.textContent : null,
    src: document.getElementById('mm-img').getAttribute('src') || '',
  };
}
"""

# Synthetic derived-shape block (dashboard/_liveclient summary keys); no
# real game id, match id, puuid or Riot ID (RM-906).
_LIVECLIENT = {
    "game_mode": "ARAM", "source": "live_api", "game_time_s": 312.0,
    "level": 9, "cs": 41, "kda": "3/2/7",
}


class _Game:
    """The game state the page sees, over /api/state-stream and
    /api/state. `live` False drops the liveclient block (game over)."""

    def __init__(self):
        self.base = self.fixture("aram")
        self.live = True

    @staticmethod
    def fixture(name):
        return json.loads((FIXTURE_DIR / f"{name}.json").read_text("utf-8"))

    def payload(self):
        d = dict(self.base)
        d["liveclient"] = dict(_LIVECLIENT) if self.live else None
        return json.dumps(d)

    def stream(self, route):
        route.fulfill(status=200, content_type="text/event-stream",
                      body="retry: 150\n\ndata: " + self.payload() + "\n\n")

    def poll(self, route):
        route.fulfill(status=200, content_type="application/json",
                      body=self.payload())


class _Crop:
    """The /api/minimap-crop stand-in. kind: 'live' answers with a small
    image as JPEG (the fast-stream cadence), 'hung' never answers (the
    route is held, not fulfilled)."""

    def __init__(self, kind):
        self.kind = kind
        self.hits = 0
        self.held = []
        self.modes = []

    def __call__(self, route):
        self.hits += 1
        q = parse_qs(urlparse(route.request.url).query)
        self.modes.append((q.get("mode") or [""])[0])
        if self.kind == "hung":
            self.held.append(route)
            return
        route.fulfill(status=200, content_type="image/jpeg",
                      body=_ICON_STAND_IN)


def _open(pw_browser, mock_server, crop, game):
    mock_server.set_fixture("aram")
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    page.add_init_script(_COUNT_JS)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route("**/api/state-stream*", game.stream)
    page.route("**/api/state?*", game.poll)
    page.route("**/api/state", game.poll)
    page.route("**/api/minimap-crop*", crop)
    page.goto(mock_server.url + "/", wait_until="domcontentloaded",
              timeout=15_000)
    # The liveclient gate opens once the routed stream lands.
    _wait_started(page, 1)
    return ctx, page, errors


def _wait_started(page, n):
    for _ in range(40):
        if (page.evaluate("() => (window.__hmMc || {}).started || 0")) >= n:
            return
        page.clock.run_for(500)
        page.wait_for_timeout(150)
    raise AssertionError(f"refreshMinimap sent fewer than {n} requests")


def _advance(page, ms):
    """Run the page clock forward, then let the polls it fired land."""
    page.clock.run_for(ms)
    page.wait_for_timeout(400)
    page.clock.run_for(500)
    page.wait_for_timeout(400)
    return page.evaluate(_WRAP_JS)


def _counts(page):
    return page.evaluate("() => Object.assign({}, window.__hmMc)")


def _release(crop):
    """Answer every held request now (a late answer)."""
    for r in crop.held:
        try:
            r.fulfill(status=200, content_type="image/jpeg",
                      body=_ICON_STAND_IN)
        except Exception:  # noqa: BLE001 - an aborted request cannot be answered
            pass
    crop.held = []


def test_a_live_feed_keeps_one_request_open_at_a_time(
    mock_server, pw_browser
):
    """Positive control: a feed that answers shows the image, not stale,
    and the poll keeps asking at the fast cadence, one request at a time."""
    crop = _Crop("live")
    ctx, page, errors = _open(pw_browser, mock_server, crop, _Game())
    try:
        w = _advance(page, 6_000)
        assert not w["hidden"] and not w["stale"], w
        assert w["caption"].startswith("ARAM"), w
        assert w["src"].startswith("blob:"), w
        c = _counts(page)
        assert c["started"] >= 8, c
        assert c["max"] == 1, c
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_hung_feed_keeps_one_request_open_and_says_stale(
    mock_server, pw_browser
):
    """The server stops answering after a live start: no more than one
    request is ever open, a hung one is given up on (the image reads
    STALE) and asked again about every 5 s, and the feed's return clears
    the STALE mark."""
    crop = _Crop("live")
    ctx, page, errors = _open(pw_browser, mock_server, crop, _Game())
    try:
        w = _advance(page, 1_000)
        assert not w["hidden"] and not w["stale"], w
        before = _counts(page)
        crop.kind = "hung"
        w = _advance(page, 15_000)
        c = _counts(page)
        assert c["max"] == 1, c
        assert c["open"] <= 1, c
        # About one new request per 5 s over 16 s, not two per second.
        assert 2 <= c["started"] - before["started"] <= 6, (before, c)
        # The last image stays up, marked STALE.
        assert not w["hidden"] and w["stale"], w
        crop.kind = "live"
        _release(crop)
        w = _advance(page, 6_000)
        assert not w["hidden"] and not w["stale"], w
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_the_game_ending_drops_the_open_request(mock_server, pw_browser):
    """A request still open when the game ends is given up on, so its late
    answer cannot show the minimap again; the next game paints anew."""
    crop = _Crop("live")
    game = _Game()
    ctx, page, errors = _open(pw_browser, mock_server, crop, game)
    try:
        w = _advance(page, 1_000)
        assert not w["hidden"], w
        crop.kind = "hung"
        _advance(page, 1_000)
        assert _counts(page)["open"] == 1, _counts(page)
        # The game ends: the stream now carries no liveclient block.
        game.live = False
        page.wait_for_timeout(1_000)
        w = _advance(page, 1_000)
        assert w["hidden"], w
        c = _counts(page)
        assert c["open"] == 0, c
        # The held request's answer lands late: the minimap stays hidden.
        crop.kind = "live"
        _release(crop)
        w = _advance(page, 3_000)
        assert w["hidden"], w
        # A new game shows it again.
        game.live = True
        page.wait_for_timeout(1_000)
        w = _advance(page, 2_000)
        assert not w["hidden"] and not w["stale"], w
        assert _counts(page)["max"] == 1, _counts(page)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_a_mode_change_drops_the_request_for_the_old_map(
    mock_server, pw_browser
):
    """A request still open when the mode moves from ARAM to SR is given up
    on at the next tick, so the old map never paints under the new mode's
    caption; the SR map paints once the feed answers."""
    crop = _Crop("live")
    game = _Game()
    ctx, page, errors = _open(pw_browser, mock_server, crop, game)
    try:
        w = _advance(page, 1_000)
        assert w["caption"].startswith("ARAM"), w
        crop.kind = "hung"
        _advance(page, 1_000)
        assert _counts(page)["open"] == 1, _counts(page)
        assert set(crop.modes) == {"aram"}, crop.modes
        game.base = _Game.fixture("sr")
        page.wait_for_timeout(1_000)
        page.clock.run_for(600)
        page.wait_for_timeout(300)
        page.clock.run_for(600)
        page.wait_for_timeout(300)
        # Well inside the 5 s timeout: the old-map request is already gone
        # and one for the new map was sent, with never two open.
        assert page.evaluate("() => document.body.dataset.mode") == "sr"
        assert "sr" in crop.modes, crop.modes
        c = _counts(page)
        assert c["max"] == 1 and c["open"] == 1, c
        crop.kind = "live"
        _release(crop)
        w = _advance(page, 2_000)
        assert w["caption"].startswith("SR"), w
        assert not w["hidden"] and not w["stale"], w
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
