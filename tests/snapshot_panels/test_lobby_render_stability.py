"""
tests/snapshot_panels/test_lobby_render_stability.py
RM-326 + RM-327 - lobby render stability + Top-8 reorder re-index.

Two rows that share one root cause: the lobby view rebuilds its
interactive rows from scratch on every render pass, so any control the
operator is holding (keyboard focus, a mid-flight confirmation class) is
destroyed underneath them.

RM-326 - the 2 s poll rebuild.
  main.js setInterval(pollLcu, 2000) -> handleLcuEnvelope ->
  _maybeRefreshLobbyView -> _lobbyViewRefresh -> _renderPartyMembers +
  _renderTop8. Both renderers cleared `ul.innerHTML` unconditionally and
  re-created every row, including the <button> controls (copy / promote /
  kick on the party list; invite / up / down / remove on Top 8). Keyboard
  focus inside either list was therefore thrown to <body> every 2 s, which
  makes both panels mouse-only and does so INVISIBLY. The same rebuild also
  truncated the 1200 ms `is-copied` confirmation class, which is the
  cheaper-to-see symptom of the identical cause.

  The fix follows the in-repo precedent (panels/champ_select.js:704 - the
  `section.dataset.csvSig === sig` idempotent render gate) rather than
  inventing a fourth pattern: compute a signature over everything the
  renderer reads and bail when nothing observable changed. A rebuild that
  DOES have to happen carries focus across itself, keyed on the stable
  data-action / data-ign / data-idx the rows already carry.

RM-327 - the Top-8 reorder buttons destroyed themselves on click.
  main.js `up` / `down` swapped two list entries, saved, then called
  _renderTop8(), which re-emitted every row with data-idx set to POSITION
  and re-bound the listeners. The clicked button was gone, focus went to
  <body>, and a repeat activation therefore moved a DIFFERENT entry back -
  the reorder ping-ponged instead of walking one entry up the list. Fixed
  by focusing the control that governs the MOVED entry at its new index
  after the re-render, so a repeat activation keeps moving the same entry.

  Two deviations from the row's literal wording, both recorded
  deliberately because they were forced by measurement.

  (1) The acceptance asked for two mouse clicks at one screen position.
  That cannot discriminate a fix - in ANY position-indexed list the pixel
  under a stationary pointer belongs to the row that took the moved
  entry's place, so a second click there swaps back no matter how the
  buttons are bound. The pointer-stationary repeat that CAN discriminate
  is the keyboard one: click once, do not move the pointer, activate the
  still-focused control again. That is exactly the affordance the
  destroyed button removed, and it is RED at HEAD.

  (2) The acceptance named the `up` control. MEASURED here 2026-09-04
  (document.elementFromPoint at each reorder button's own centre): every
  `up` chevron in the Top-8 panel reports its sibling `down` button as the
  hit target, in all three rows, disabled or not. Cause is CSS, not JS -
  web/css/panels/header.css:1170 gives .lv-top8-reorder-btn a 44x44
  ::before hit-target overlay on a 26x14 button, so the two stacked
  overlays overlap and `down` (later in DOM order, no z-index) wins. That
  is a separate defect owned by web/css and NOT touched here. The mouse
  half of the acceptance therefore drives `down`, which is genuinely
  reachable; a sibling keyboard-only test covers the `up` handler.

Drive path mirrors test_lobby_view.py: /?ui_mock=1#lobby with an empty SSE
state so the auto-derive lands on "home" and the #lobby hash wins the
router. Under ui_mock the party block is painted from
/data/ui_mock/lobby.json, so the poll cycles re-render UNCHANGED fixture
data - which is precisely the condition the render gate must recognise.
The Top 8 is seeded through a routed /api/top8 (the panel's real
server-backed store) rather than by poking module-private state.
"""
import copy
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent.parent

# Polled LCU envelope. phase "Lobby" keeps _viewAutoDerive on "lobby"
# (main.js:761) so the poll chain reaches _maybeRefreshLobbyView instead of
# routing the page off the surface under test. Deliberately carries NO
# `top8` key - _top8Load() short-circuits on state.latest.lcu.top8, which
# would bypass the /api/top8 store the reorder tests drive.
_POLL_LCU = {
    "phase": "Lobby",
    "lobby": {
        "queue_id": 420,
        "queue_name": "Ranked Solo/Duo",
        "party_size": 3,
        "max_party_size": 5,
        "is_leader": True,
        "party_type": "open",
        "search_state": "Idle",
        "members": [
            {"riot_id": "SamplePlayer#Trist", "summoner_name": "SamplePlayer",
             "is_self": True, "is_leader": True, "summoner_level": 372},
            {"riot_id": "Brawler#NA1", "summoner_name": "Brawler",
             "is_self": False, "is_leader": False, "summoner_level": 218},
        ],
    },
}

# Three Top-8 entries in a known order. Names are distinct first tokens so
# the rendered .lv-top8-name cell (fullId.split("#")[0]) reads back as an
# unambiguous order.
_TOP8_SEED = [
    {"riot_id": "Alpha#AAA", "summoner_name": "Alpha",
     "games_with_me": 11, "preferred_role": "TOP", "rank": None},
    {"riot_id": "Bravo#BBB", "summoner_name": "Bravo",
     "games_with_me": 22, "preferred_role": "MIDDLE", "rank": None},
    {"riot_id": "Charlie#CCC", "summoner_name": "Charlie",
     "games_with_me": 33, "preferred_role": "UTILITY", "rank": None},
]

# Joined rendered Top-8 order. Placeholder slots carry no .lv-top8-name.
_TOP8_ORDER_JS = (
    "Array.from(document.querySelectorAll("
    "'#lv-top8-list .lv-top8-name'))"
    ".map(function (e) { return e.textContent.trim(); }).join(',')"
)

# Witness that _lobbyViewRefresh actually ran, independent of the two
# renderers under test: the refresh re-assigns #lv-queue-name.textContent
# on every pass (main.js:5280), and the textContent setter always replaces
# the child text node, so childList fires once per refresh. Without this
# the "survives N ticks" assertions could pass vacuously by never ticking.
_REFRESH_WITNESS_JS = """
() => {
  window.__rmRefreshTicks = 0;
  const q = document.querySelector('#lv-queue-name');
  if (!q) return false;
  const obs = new MutationObserver((recs) => {
    window.__rmRefreshTicks += recs.length;
  });
  obs.observe(q, { childList: true });
  window.__rmRefreshObs = obs;
  return true;
}
"""


def _open_lobby_stability(
    pw_browser, mock_server, top8=None, poll=False, ui_mock=True, lcu=None
):
    """Open the lobby view with optional /api/top8 seeding and optional
    LCU polling. Returns (ctx, page, errors, state_hits).

    `lcu` is a live dict the caller may mutate between poll cycles - the
    route handler re-serialises it on every hit, so a mutation lands on
    the next tick and forces a genuine (non-gated) re-render."""
    import json as _json

    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )

    state_hits: list = []
    top8_store = {"entries": list(top8 or [])}
    envelope = _POLL_LCU if lcu is None else lcu

    def _handle_state(route, request):
        state_hits.append(1)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"lcu": envelope}),
        )

    def _handle_top8(route, request):
        if request.method == "POST":
            try:
                posted = _json.loads(request.post_data or "{}")
            except ValueError:
                posted = {}
            if isinstance(posted.get("entries"), list):
                top8_store["entries"] = posted["entries"]
        route.fulfill(
            status=200,
            content_type="application/json",
            body=_json.dumps({"ok": True, "entries": top8_store["entries"]}),
        )

    if poll:
        ctx.route(lambda u: urlsplit(u).path == "/api/state", _handle_state)
    if top8 is not None:
        ctx.route(lambda u: urlsplit(u).path == "/api/top8", _handle_top8)

    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    page.goto(
        mock_server.url + ("/?ui_mock=1#lobby" if ui_mock else "/#lobby"),
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "document.querySelector('#lv-queue-name') && "
        "document.querySelector('#lv-queue-name').textContent.trim() "
        "!== '-' && "
        "document.querySelector('#lv-queue-name').textContent.trim() "
        "!== ''",
        timeout=10_000,
    )
    return ctx, page, errors, state_hits


def _arm_refresh_witness(page):
    assert page.evaluate(_REFRESH_WITNESS_JS), "#lv-queue-name absent"


def _wait_refresh_ticks(page, n, timeout_ms=30_000):
    """Block until n further _lobbyViewRefresh passes have been observed."""
    page.wait_for_function(
        f"window.__rmRefreshTicks >= {n}", timeout=timeout_ms
    )


# --------------------------------------------------------------------
# RM-326 - the 2 s poll rebuild
# --------------------------------------------------------------------
def test_party_rows_survive_poll_ticks(mock_server, pw_browser):
    """Node identity across two poll cycles with UNCHANGED fixture data.

    The strong observable for RM-326: hold a reference to the first party
    <li>, let two lobby refreshes run, and assert the SAME node is still
    mounted. At HEAD _renderPartyMembers clears innerHTML unconditionally
    (main.js:4618), so the held node is detached on the first tick."""
    ctx, page, errors, hits = _open_lobby_stability(
        pw_browser, mock_server, poll=True
    )
    try:
        page.wait_for_function(
            "document.querySelectorAll("
            "'#lv-members-list .lobby-member-row').length > 0",
            timeout=10_000,
        )
        _arm_refresh_witness(page)
        page.evaluate(
            "window.__rmFirstRow = document.querySelector("
            "'#lv-members-list .lobby-member-row')"
        )
        _wait_refresh_ticks(page, 2)

        # Provenance: the refreshes came off the 2 s LCU poller, not a
        # one-shot boot render.
        assert len(hits) >= 2, (
            f"expected >=2 /api/state poll hits, got {len(hits)}"
        )
        still_mounted = page.evaluate(
            "!!(window.__rmFirstRow && window.__rmFirstRow.isConnected)"
        )
        same_node = page.evaluate(
            "window.__rmFirstRow === document.querySelector("
            "'#lv-members-list .lobby-member-row')"
        )
        ticks = page.evaluate("window.__rmRefreshTicks")
        assert still_mounted, (
            f"party row node detached after {ticks} lobby refreshes - "
            "_renderPartyMembers rebuilt unchanged fixture data"
        )
        assert same_node, (
            f"party row node replaced after {ticks} lobby refreshes - "
            "_renderPartyMembers rebuilt unchanged fixture data"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [party identity]: {errors[:3]}"


def test_party_action_keeps_focus_across_poll_ticks(mock_server, pw_browser):
    """Focus survives the poll rebuild.

    Focus the party row's copy control, drive two poll cycles, and assert
    document.activeElement is still that control. At HEAD the button is
    destroyed and focus silently falls back to <body> - which is what makes
    the panel keyboard-unusable without any visible symptom."""
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, poll=True
    )
    try:
        sel = "#lv-members-list .lv-member-action[data-action=\"copy\"]"
        page.wait_for_function(
            f"document.querySelectorAll('{sel}').length > 0", timeout=10_000
        )
        _arm_refresh_witness(page)
        focused_ign = page.evaluate(
            "(() => {"
            f"  const b = document.querySelector('{sel}');"
            "   b.focus();"
            "   return b.dataset.ign || '';"
            "})()"
        )
        assert focused_ign, "copy control carries no data-ign to key focus on"
        assert page.evaluate(
            f"document.activeElement === document.querySelector('{sel}')"
        ), "focus() did not land on the copy control"

        _wait_refresh_ticks(page, 2)

        active = page.evaluate(
            "(() => {"
            "  const a = document.activeElement;"
            "  return {"
            "    tag: a ? a.tagName : null,"
            "    action: (a && a.dataset) ? (a.dataset.action || '') : '',"
            "    ign: (a && a.dataset) ? (a.dataset.ign || '') : '',"
            "  };"
            "})()"
        )
        ticks = page.evaluate("window.__rmRefreshTicks")
        assert active["action"] == "copy" and active["ign"] == focused_ign, (
            f"keyboard focus lost after {ticks} lobby refreshes - "
            f"activeElement is {active!r}, expected the copy control for "
            f"{focused_ign!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [party focus]: {errors[:3]}"


def test_party_focus_survives_a_real_rebuild(mock_server, pw_browser):
    """The other half of RM-326: focus carry on a rebuild that DOES have
    to happen.

    The render gate only covers the no-change case; when the party data
    genuinely changes the rows must still be re-created, and that rebuild
    would drop focus to <body> exactly as the 2 s churn did. Drive the
    live LCU feed (no ui_mock, so the party list reads the polled
    envelope), focus a copy control, then mutate a rendered field so the
    signature changes and the rebuild fires for real.

    Guards against the gate making _lvRestoreFocus dead code: without the
    focus carry this is RED even with the gate in place."""
    lcu = copy.deepcopy(_POLL_LCU)
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, poll=True, ui_mock=False, lcu=lcu
    )
    try:
        sel = "#lv-members-list .lv-member-action[data-action=\"copy\"]"
        page.wait_for_function(
            f"document.querySelectorAll('{sel}').length >= 2", timeout=15_000
        )
        page.wait_for_function(
            "document.querySelector('#lv-members-list')"
            ".textContent.indexOf('LVL 218') >= 0",
            timeout=15_000,
        )
        focused_ign = page.evaluate(
            "(() => {"
            "  const b = document.querySelector("
            "    '#lv-members-list "
            "[data-action=\"copy\"][data-ign=\"Brawler#NA1\"]');"
            "  if (!b) return '';"
            "  b.focus();"
            "  return b.dataset.ign;"
            "})()"
        )
        assert focused_ign == "Brawler#NA1", (
            f"could not focus the Brawler copy control ({focused_ign!r})"
        )

        # Mutate a rendered field -> signature changes -> real rebuild.
        lcu["lobby"]["members"][1]["summoner_level"] = 219
        page.wait_for_function(
            "document.querySelector('#lv-members-list')"
            ".textContent.indexOf('LVL 219') >= 0",
            timeout=20_000,
        )

        active = page.evaluate(
            "(() => {"
            "  const a = document.activeElement;"
            "  return {"
            "    action: (a && a.dataset) ? (a.dataset.action || '') : '',"
            "    ign: (a && a.dataset) ? (a.dataset.ign || '') : '',"
            "  };"
            "})()"
        )
        assert active["action"] == "copy" and active["ign"] == "Brawler#NA1", (
            "focus was not carried across a genuine party rebuild - "
            f"activeElement is {active!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [party rebuild focus]: {errors[:3]}"


def test_top8_rows_survive_poll_ticks(mock_server, pw_browser):
    """Same rebuild, second render site: _renderTop8 (main.js:5498) clears
    innerHTML on every refresh too, so the invite / reorder / remove
    controls are destroyed on the same 2 s cadence."""
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, top8=_TOP8_SEED, poll=True
    )
    try:
        page.wait_for_function(
            f"({_TOP8_ORDER_JS}) === 'Alpha,Bravo,Charlie'", timeout=10_000
        )
        _arm_refresh_witness(page)
        page.evaluate(
            "window.__rmTop8Row = document.querySelector("
            "'#lv-top8-list .lv-top8-row:not(.is-placeholder)')"
        )
        _wait_refresh_ticks(page, 2)

        same_node = page.evaluate(
            "!!(window.__rmTop8Row && window.__rmTop8Row.isConnected) && "
            "window.__rmTop8Row === document.querySelector("
            "'#lv-top8-list .lv-top8-row:not(.is-placeholder)')"
        )
        ticks = page.evaluate("window.__rmRefreshTicks")
        assert same_node, (
            f"Top-8 row node replaced after {ticks} lobby refreshes - "
            "_renderTop8 rebuilt an unchanged list"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 identity]: {errors[:3]}"


# --------------------------------------------------------------------
# RM-327 - Top-8 reorder
# --------------------------------------------------------------------
def _seed_top8(mock_server, pw_browser):
    ctx, page, errors, _hits = _open_lobby_stability(
        pw_browser, mock_server, top8=_TOP8_SEED
    )
    page.wait_for_function(
        f"({_TOP8_ORDER_JS}) === 'Alpha,Bravo,Charlie'", timeout=10_000
    )
    return ctx, page, errors


def _active_control(page):
    return page.evaluate(
        "(() => {"
        "  const a = document.activeElement;"
        "  return {"
        "    tag: a ? a.tagName : null,"
        "    action: (a && a.dataset) ? (a.dataset.action || '') : '',"
        "    idx: (a && a.dataset) ? (a.dataset.idx || '') : '',"
        "    inList: !!(a && a.closest && a.closest('#lv-top8-list')),"
        "  };"
        "})()"
    )


def _settle_order(page, want, timeout_ms=5_000):
    """Wait (bounded) for the rendered order, but never fail on the wait -
    the caller asserts on the observed value so a red run reports the
    order it actually got."""
    try:
        page.wait_for_function(
            f"({_TOP8_ORDER_JS}) === '{want}'", timeout=timeout_ms
        )
    except Exception:  # noqa: BLE001 - assert on the value, not the wait
        pass
    return page.evaluate(_TOP8_ORDER_JS)


def test_top8_reorder_repeat_moves_same_entry(mock_server, pw_browser):
    """Repeat activation walks ONE entry through the list, not back.

    Seed [Alpha, Bravo, Charlie]; click the down control at index 0 once
    with the mouse, then - WITHOUT moving the pointer - activate the
    still-focused control again from the keyboard. Alpha must keep
    travelling: [Bravo, Charlie, Alpha], which differs from the start.

    At HEAD the first click destroys the control it was fired from, focus
    drops to <body>, the second activation is swallowed, and the list is
    left one move in at [Bravo, Alpha, Charlie]."""
    ctx, page, errors = _seed_top8(mock_server, pw_browser)
    try:
        start = page.evaluate(_TOP8_ORDER_JS)
        assert start == "Alpha,Bravo,Charlie", f"bad seed order {start!r}"

        page.locator(
            "#lv-top8-list [data-action=\"down\"][data-idx=\"0\"]"
        ).click()
        page.wait_for_function(
            f"({_TOP8_ORDER_JS}) === 'Bravo,Alpha,Charlie'", timeout=5_000
        )

        # No pointer movement between the two activations: the second one
        # is a keypress on whatever the first click left focused.
        page.keyboard.press("Enter")
        final = _settle_order(page, "Bravo,Charlie,Alpha")

        assert final == "Bravo,Charlie,Alpha", (
            "repeat reorder did not keep moving the same entry: "
            f"start {start!r} -> final {final!r} (expected "
            "'Bravo,Charlie,Alpha')"
        )
        assert final != start, (
            f"two reorder activations left the order unchanged ({final!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 repeat reorder]: {errors[:3]}"


def test_top8_reorder_keeps_focus_after_click(mock_server, pw_browser):
    """Companion to the repeat-reorder acceptance: after ONE mouse click
    the focused element is still a reorder control, and it is the one that
    now governs the entry that just moved (Alpha, index 1)."""
    ctx, page, errors = _seed_top8(mock_server, pw_browser)
    try:
        page.locator(
            "#lv-top8-list [data-action=\"down\"][data-idx=\"0\"]"
        ).click()
        page.wait_for_function(
            f"({_TOP8_ORDER_JS}) === 'Bravo,Alpha,Charlie'", timeout=5_000
        )
        active = _active_control(page)
        assert active["action"] == "down" and active["inList"], (
            f"focus left the reorder control after a click: {active!r}"
        )
        assert active["idx"] == "1", (
            "focus did not follow the moved entry to its new index: "
            f"{active!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 reorder focus]: {errors[:3]}"


def test_top8_reorder_up_repeat_moves_same_entry(mock_server, pw_browser):
    """Same acceptance for the `up` handler, driven from the keyboard.

    `up` cannot be mouse-driven at all today (see the module docstring:
    its sibling `down` overlay owns the hit target), so this covers the
    other half of the reorder pair the only way an operator can reach it:
    focus the control, activate it, and activate it again without touching
    anything else. Charlie must reach the top: [Charlie, Alpha, Bravo].

    At HEAD the first activation destroys the button, focus falls to
    <body>, and the list stops at [Alpha, Charlie, Bravo]."""
    ctx, page, errors = _seed_top8(mock_server, pw_browser)
    try:
        start = page.evaluate(_TOP8_ORDER_JS)
        page.evaluate(
            "document.querySelector("
            "'#lv-top8-list [data-action=\"up\"][data-idx=\"2\"]').focus()"
        )
        page.keyboard.press("Enter")
        page.wait_for_function(
            f"({_TOP8_ORDER_JS}) === 'Alpha,Charlie,Bravo'", timeout=5_000
        )
        page.keyboard.press("Enter")
        final = _settle_order(page, "Charlie,Alpha,Bravo")

        assert final == "Charlie,Alpha,Bravo", (
            "repeat up-reorder did not keep moving the same entry: "
            f"start {start!r} -> final {final!r} (expected "
            "'Charlie,Alpha,Bravo')"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 up repeat]: {errors[:3]}"


def test_top8_reorder_reindexes_rows(mock_server, pw_browser):
    """Regression guard, green at HEAD by design.

    RM-327's own note: the reorder controls need re-indexing after a move
    REGARDLESS of how the 2 s rebuild is gated. This pins that - after a
    reorder every real row's data-idx equals its DOM position and every
    control inside it carries the same idx - so the RM-326 render gate can
    never ship stale data-idx attributes on reused nodes (which would make
    a later click move the wrong entry)."""
    ctx, page, errors = _seed_top8(mock_server, pw_browser)
    try:
        page.locator(
            "#lv-top8-list [data-action=\"down\"][data-idx=\"0\"]"
        ).click()
        page.wait_for_function(
            f"({_TOP8_ORDER_JS}) === 'Bravo,Alpha,Charlie'", timeout=5_000
        )
        bad = page.evaluate(
            "(() => {"
            "  const rows = Array.from(document.querySelectorAll("
            "    '#lv-top8-list .lv-top8-row'));"
            "  const out = [];"
            "  rows.forEach((li, pos) => {"
            "    if (li.classList.contains('is-placeholder')) return;"
            "    if (li.dataset.idx !== String(pos)) {"
            "      out.push('row ' + pos + ' data-idx=' + li.dataset.idx);"
            "    }"
            "    li.querySelectorAll('[data-idx]').forEach((c) => {"
            "      if (c.dataset.idx !== String(pos)) {"
            "        out.push('row ' + pos + ' ' + c.dataset.action +"
            "                 ' data-idx=' + c.dataset.idx);"
            "      }"
            "    });"
            "  });"
            "  return out;"
            "})()"
        )
        assert bad == [], f"stale data-idx after reorder: {bad}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 reindex]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in this
    slice's authored test file."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s) in {__file__}: {offenders[:5]}"
