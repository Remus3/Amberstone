"""
tests/snapshot_panels/test_lobby_duo_synergy_rm881.py
RM-881 (b) (QA23): the lobby re-fires duo synergy when the party size
reaches 2.

Headless render of the Pre-Game Lobby under ui_mock (the ui_mock lobby
fixture is a party of 3), driven through the same harness as
test_lobby_view.py. Under ui_mock the controller in
web/js/panels/lobby_duo_synergy.js reads the page's own
web/data/ui_mock/duo_synergy.json instead of /api/duo-synergy; the request
contract (party size, my_role, one fetch per party episode, degraded
states) is pinned by web/js/panels/lobby_duo_synergy.test.mjs.

The assertions are the 5-phase UI-fixture audit on the rendered block:
STRUCTURE (two labeled rows of four cells inside the PARTY card, the card
still inside the 1920x1080 viewport, no cell spilling out of the card),
TYPOGRAPHY (no text under --fs-xs, 16 px), HIT-TARGETS (the block is
read-only: no focusable control in it), ASCII (rendered text), HIERARCHY
(title, then BOT, then SUPPORT, top to bottom). It also checks that
repeated lobby refreshes for the same party do not re-fire the fetch. A
plain wait does not reliably add a refresh here (the mock store is empty,
so pollLcu never calls handleLcuEnvelope, and the HTTP state fallback only
starts after 4 s without a frame), so the test drives the refreshes and
proves each one ran (RM-1092).
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.test_lobby_view import _open_lobby

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = json.loads(
    (ROOT / "web" / "data" / "ui_mock" / "duo_synergy.json")
    .read_text(encoding="utf-8"))
SCREENSHOTS = Path(__file__).parent / "screenshots"

_MEASURE = """() => {
  const box = document.getElementById('lv-duo-synergy');
  const card = box && box.closest('.lobby-view-card-party');
  const r = (e) => { const b = e.getBoundingClientRect();
    return {top: b.top, bottom: b.bottom, left: b.left, right: b.right}; };
  const texts = [];
  if (box) {
    const walk = document.createTreeWalker(box, NodeFilter.SHOW_TEXT);
    let n;
    while ((n = walk.nextNode())) {
      if (!n.textContent.trim()) continue;
      const cs = getComputedStyle(n.parentElement);
      texts.push({text: n.textContent,
                  px: parseFloat(cs.fontSize),
                  cls: n.parentElement.className});
    }
  }
  return {
    hidden: !box || box.hidden,
    visible: !!box && box.offsetParent !== null,
    rows: box ? box.querySelectorAll('.lv-duosyn-row').length : 0,
    cells: box ? [...box.querySelectorAll('.lv-duosyn-cell')].map((c) => ({
      name: c.querySelector('.lv-duosyn-name').textContent,
      rect: r(c)})) : [],
    roles: box ? [...box.querySelectorAll('.lv-duosyn-role')]
      .map((e) => ({text: e.textContent, top: r(e).top})) : [],
    title: box && box.querySelector('.lv-duosyn-title')
      ? {text: box.querySelector('.lv-duosyn-title').textContent,
         top: r(box.querySelector('.lv-duosyn-title')).top} : null,
    focusables: box ? box.querySelectorAll(
      'a,button,input,select,textarea,[tabindex]').length : -1,
    card: card ? r(card) : null,
    box: box ? r(box) : null,
    vh: window.innerHeight,
    duo: performance.getEntriesByType('resource').map((e) => e.name)
      .filter((u) => u.includes('duo_synergy.json')
        || u.includes('/api/duo-synergy')),
    texts,
  };
}"""


# RM-1092: at least one lobby refresh per loop, proven. Each loop leaves
# #lobby, overwrites the queue name with a sentinel, and comes back.
# _lobbyViewRefresh is the only writer of #lv-queue-name in web/js, so the
# name repainted means it ran again for the same party. The router's lobby
# activation (main.js `if (viewId === "lobby") { _lobbyViewWireOnce();
# _lobbyViewRefresh(); }`) is the expected caller; the HTTP state fallback
# (handleLcuEnvelope -> _maybeRefreshLobbyView) also repaints it once it
# starts, so the proof is about the refresh, not about which caller ran it.
_SENTINEL = "__s144q23__"


def _drive_lobby_refreshes(page, n):
    done = 0
    for _ in range(n):
        page.evaluate("() => { location.hash = '#home'; }")
        page.wait_for_function(
            "document.body.dataset.view === 'home'", timeout=10_000)
        page.evaluate(
            "(s) => { document.getElementById('lv-queue-name')"
            ".textContent = s; }", _SENTINEL)
        page.evaluate("() => { location.hash = '#lobby'; }")
        page.wait_for_function(
            "(s) => document.body.dataset.view === 'lobby'"
            " && document.getElementById('lv-queue-name').textContent"
            ".trim() !== '' && document.getElementById('lv-queue-name')"
            ".textContent !== s", arg=_SENTINEL, timeout=10_000)
        done += 1
    return done


def test_lobby_duo_synergy_renders_at_party_size_2_plus(
        mock_server, pw_browser):
    ctx, page, errors = _open_lobby(pw_browser, mock_server)
    try:
        page.wait_for_function(
            "document.querySelectorAll('#lv-duo-synergy .lv-duosyn-cell')"
            ".length === 8",
            timeout=10_000,
        )
        # RM-1092: a plain wait here did not reliably add a refresh
        # (see the module docstring), so drive the extra refreshes for the
        # same party and prove each one ran.
        refreshes = _drive_lobby_refreshes(page, 2)
        # Margin for a late duplicate duo fetch to reach Resource Timing.
        page.wait_for_timeout(750)
        m = page.evaluate(_MEASURE)
        lane_pair = page.evaluate(_LANE_PAIR)
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator(".lobby-view-card-party").screenshot(
            path=str(SCREENSHOTS / "lobby_duo_synergy_rm881.png"))
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [lobby duo]: {errors[:3]}"

    # STRUCTURE
    assert not m["hidden"] and m["visible"], m
    assert m["rows"] == 2, m
    want = [c["champ"] for c in FIXTURE["top_row"] + FIXTURE["bottom_row"]]
    assert [c["name"] for c in m["cells"]] == want
    card, box = m["card"], m["box"]
    assert card["top"] <= box["top"] and box["bottom"] <= card["bottom"] + 1
    for c in m["cells"]:
        assert card["left"] - 1 <= c["rect"]["left"], c
        assert c["rect"]["right"] <= card["right"] + 1, c
    assert card["bottom"] <= m["vh"], (card, m["vh"])

    # TYPOGRAPHY: nothing under the --fs-xs floor.
    assert m["texts"], m
    small = [t for t in m["texts"] if t["px"] < 16]
    assert not small, small

    # HIT-TARGETS: read-only block.
    assert m["focusables"] == 0, m

    # ASCII
    for t in m["texts"]:
        assert t["text"].isascii(), t

    # HIERARCHY: title above BOT above SUPPORT.
    assert m["title"]["text"] == "DUO PICKS"
    roles = m["roles"]
    assert [x["text"] for x in roles] == ["BOT", "SUPPORT"]
    assert m["title"]["top"] < roles[0]["top"] < roles[1]["top"]

    # One fetch for this party episode, the fixture not the live route,
    # across the mock-landing refresh plus the driven ones: >= 3 refreshes
    # of the same party of 3 (the view-entry refresh before the mock lands
    # has no lobby and does not count). The per-refresh proof is the
    # sentinel wait in _drive_lobby_refreshes, which raises on a timeout;
    # this line only records the count. Resource Timing covers the fetch
    # even though it fired during goto.
    assert refreshes == 2, refreshes
    duo = m["duo"]
    assert len(duo) == 1, duo
    assert duo[0].endswith("/data/ui_mock/duo_synergy.json"), duo

    # RM-1088 positive control for the non-SR renders below: the SR
    # lobby (queue 420) shows the lane-pair control on the same gate.
    assert lane_pair == {"exists": True, "shown": True}, lane_pair


# RM-1088 (queue lane cycle 4 filing): the real main.js queue gate.
# The node tests cover the gate with a stand-in predicate, and the render
# above is the ui_mock SR lobby (queue 420), so deleting the main.js
# `isDuoQueue: (qid) => SR_QUEUE_IDS.has(qid)` line stayed green: the
# controller then defaults to "every queue" and an ARAM / Arena party
# fetches and shows BOT / SUPPORT picks. These renders swap the page's
# lobby.json for the same party of 3 in a non-SR queue (ARAM 450, Arena
# 1750; the tracked fixture is not edited) and assert the block stays
# hidden and no duo request is made, through the real wiring.
_LANE_PAIR = """() => {
  const e = document.querySelector('#lv-queue-controls .lq-lane-pair');
  return {exists: !!e, shown: !!e && e.offsetParent !== null
    && !e.classList.contains('hidden')};
}"""

_NON_SR_LOBBIES = {
    450: "ARAM",
    1750: "Arena",
}


def _non_sr_lobby_body(queue_id):
    body = json.loads(
        (ROOT / "web" / "data" / "ui_mock" / "lobby.json")
        .read_text(encoding="utf-8"))
    assert body["lobby"]["party_size"] >= 2, body["lobby"]
    body["lobby"]["queue_id"] = queue_id
    body["lobby"]["queue_name"] = _NON_SR_LOBBIES[queue_id]
    return json.dumps(body)


def _open_non_sr_lobby(pw_browser, mock_server, queue_id):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Same router drive as test_lobby_view._open_lobby, plus a route that
    # serves the non-SR lobby variant. Registered before navigation.
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    served = []
    body = _non_sr_lobby_body(queue_id)

    def _handle_lobby(route, request):
        served.append(request.url)
        route.fulfill(status=200, content_type="application/json", body=body)

    ctx.route("**/data/ui_mock/lobby.json*", _handle_lobby)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/?ui_mock=1#lobby",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(n) => { const e = document.querySelector('#lv-queue-name');"
        " return !!e && e.textContent.trim() === n.toUpperCase(); }",
        arg=_NON_SR_LOBBIES[queue_id],
        timeout=10_000,
    )
    return ctx, page, errors, served


@pytest.mark.parametrize("queue_id", sorted(_NON_SR_LOBBIES))
def test_lobby_duo_synergy_stays_hidden_in_a_non_sr_queue(
        mock_server, pw_browser, queue_id):
    ctx, page, errors, served = _open_non_sr_lobby(
        pw_browser, mock_server, queue_id)
    try:
        # The party roster rendered, so the refresh that calls the duo
        # controller ran on this lobby. With an empty mock store the page
        # runs that refresh on view entry and when the mock lands, not on
        # the 2 s LCU poll; the wait is a margin for a late duo fetch.
        page.wait_for_function(
            "document.querySelectorAll("
            "'#lv-members-list .lobby-member-row:not(.is-placeholder)')"
            ".length >= 2",
            timeout=10_000,
        )
        page.wait_for_timeout(2_500)
        m = page.evaluate(_MEASURE)
        lane_pair = page.evaluate(_LANE_PAIR)
    finally:
        page.close()
        ctx.close()

    assert not errors, f"JS errors [lobby duo {queue_id}]: {errors[:3]}"
    # The variant really was the lobby the page rendered.
    assert served, "the non-SR lobby.json route was never requested"
    # Same-root sibling: the lane-pair control is gated on the same
    # SR_QUEUE_IDS set (main.js `showLanes`) and had no headless render
    # either. Hidden here; shown in the SR render above.
    assert lane_pair == {"exists": True, "shown": False}, lane_pair

    # The gate: no duo request of either kind, and the block stays empty.
    assert m["duo"] == [], m["duo"]
    assert m["hidden"] and not m["visible"], m
    assert m["rows"] == 0 and m["cells"] == [], m
