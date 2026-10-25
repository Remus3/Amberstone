"""
tests/snapshot_panels/test_tft_active_match_view.py
Active Match view during a LIVE TFT game, rendered in headless Chromium from
REAL recorded states (session 134, lane uiux).

TFT runs as a standalone TFTClient with nothing on :2999, so /api/state carries
lcu.phase InProgress with an empty liveclient for the whole match. The session
134 TFT QA recorder captured two row shapes (fixtures/tft_live_s134*.json):
  - tft_live_s134.json         mode_key tft, every TFT coach field empty
                               (2 of 83 rows);
  - tft_live_s134_client.json  mode_key client (RC lost the TFT mode after a
                               restart) with a stale SR coach payload whose
                               action is "Drake spawns 5:00 - set up vision"
                               plus SR callouts (81 of 83 rows).
Both used to paint SR scaffolding mid-game. The page contract is the S134 T1
no-feed fallback in web/js/panels/active_match.js (amLiveFallbackModel /
_amRenderLiveFallback / amStickyPhase): an honest status row, a fixed STAGE /
LEVEL / HP / GOLD strip in TFT, TFT placeholders in BUILD / MAP, the League-only
strips hidden, and never a coach imperative. web/js/panels/
active_match_tft.test.mjs pins the pure model; this file pins what the real
page renders from the real rows, end to end through main.js.

Drive path: the mock server's /api/state carries lcu.phase InProgress, so the
view router auto-derives #active-match. Both state handlers in main.js stamp
state.latest.lcu BEFORE onState (RM-898), so the live branch lands on the
FIRST state tick; the two first-tick tests at the end pin that. Every wait
below is on a state tick or a rendered value, never a fixed sleep.
"""
import copy
import json
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

FIXTURES = Path(__file__).parent / "fixtures"

_LIVE_TICK_MS = 20_000

# Text that only the League panes paint. None of it may appear in the Active
# Match view during a live game with no :2999 feed.
_LOL_ONLY = (
    "DS engine ranks",
    "WARDS",
    "MIA",
    "waiting for live data",
    "Static mode map",
    "FAIR FIGHT",
)

# The live SR imperatives the real client-mode row carries (coach.action /
# coach.immediate / callouts / lead_projection). B4: none may be visible
# anywhere on the page while the game is live.
_SR_IMPERATIVES = (
    "Drake spawns",
    "Rift Herald",
    "ward both pits",
    "farm cleanly",
)

_FALLBACK_HEAD = "#am-call-body [data-am-fallback]"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _open(mock_server, pw_browser, data: dict, init_scripts: tuple = ()):
    mock_server._store["data"] = data
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    for script in init_scripts:
        page.add_init_script(script)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/", wait_until="domcontentloaded", timeout=15_000)
    return ctx, page, errors


def _wait_fallback(page, kind: str) -> None:
    page.wait_for_function(
        "(k) => document.querySelector("
        f"{json.dumps(_FALLBACK_HEAD)})?.dataset.amFallback === k",
        arg=kind,
        timeout=_LIVE_TICK_MS,
    )


def _text(page, host_id: str) -> str:
    return page.evaluate(
        "(id) => document.getElementById(id).innerText", host_id
    )


def _display(page, el_id: str) -> str:
    return page.evaluate(
        "(id) => { const e = document.getElementById(id);"
        " return e ? getComputedStyle(e).display : 'absent'; }",
        el_id,
    )


def _stat_cells(page) -> list[list]:
    """[label, value, is-empty] per .am-tft-stat cell, in DOM order."""
    return page.evaluate(
        "() => Array.from(document.querySelectorAll("
        "'#am-call-body .am-tft-stat')).map(c => ["
        "c.querySelector('.am-tft-stat-label').textContent,"
        "c.querySelector('.am-tft-stat-value').textContent,"
        "c.classList.contains('is-empty')])"
    )


def _wait_state_ticks(page, n: int) -> None:
    """Block until the page has fetched /api/state n more times."""
    for _ in range(n):
        with page.expect_response(
            lambda r: r.url.split("?")[0].endswith("/api/state"),
            timeout=_LIVE_TICK_MS,
        ):
            pass


def test_real_tft_row_renders_the_honest_tft_fallback(mock_server, pw_browser):
    """mode_key tft, every TFT coach field empty: the TFT status row, a STAGE /
    LEVEL / HP / GOLD strip of dashes, TFT placeholders in BUILD / MAP, and no
    League surface - and a later state tick rebuilds nothing."""
    ctx, page, errors = _open(mock_server, pw_browser, _load("tft_live_s134"))
    try:
        _wait_fallback(page, "tft")
        assert page.evaluate("document.body.dataset.view") == "active-match"
        assert page.locator("#view-active-match").is_visible()
        assert _text(page, "am-sub") == (
            "TFT - phase InProgress - live data unavailable"
        )
        head = page.locator(_FALLBACK_HEAD)
        assert head.get_attribute("role") == "status"
        head_text = head.inner_text()
        assert "TFT LIVE DATA" in head_text
        assert "no live feed from the TFT client yet" in head_text
        assert _stat_cells(page) == [
            ["STAGE", "-", True], ["LEVEL", "-", True],
            ["HP", "-", True], ["GOLD", "-", True],
        ]
        assert _text(page, "am-build-body").strip() == "No League item build in TFT."
        assert _text(page, "am-map-body").strip() == "No map intel in TFT."

        view = _text(page, "view-active-match")
        for needle in _LOL_ONLY:
            assert needle not in view, f"League text {needle!r} in live TFT view"
        for wid in ("am-ward-heat", "am-spike-curve", "am-draft-elo"):
            disp = _display(page, wid)
            assert disp in ("none", "absent"), f"#{wid} display={disp!r} in TFT"

        # A state tick with the same payload is a no-op: the signature guard
        # keeps the very same nodes (no churn, no focus loss).
        page.evaluate(
            "() => { document.querySelector("
            f"{json.dumps(_FALLBACK_HEAD)})._amProbe = 1;"
            " document.getElementById('am-map-body').firstElementChild"
            "._amProbe = 1; }"
        )
        _wait_state_ticks(page, 2)
        kept = page.evaluate(
            "() => [document.querySelector("
            f"{json.dumps(_FALLBACK_HEAD)})?._amProbe,"
            " document.getElementById('am-map-body').firstElementChild"
            "?._amProbe]"
        )
        assert kept == [1, 1], f"fallback panes rebuilt on an unchanged tick: {kept}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_real_client_row_paints_no_sr_imperative_anywhere(mock_server, pw_browser):
    """mode_key client + lcu InProgress + liveclient {} (81 of 83 real rows):
    the mode-not-detected status, no TFT strip, and none of the stale SR
    imperatives the payload carries is visible ANYWHERE on the page."""
    ctx, page, errors = _open(
        mock_server, pw_browser, _load("tft_live_s134_client")
    )
    try:
        _wait_fallback(page, "game")
        assert page.evaluate("document.body.dataset.view") == "active-match"
        assert _text(page, "am-sub") == (
            "GAME IN PROGRESS - mode not detected - live data unavailable"
        )
        head_text = page.locator(_FALLBACK_HEAD).inner_text()
        assert "LIVE DATA" in head_text
        assert "RC has no live feed for this game yet" in head_text
        assert _stat_cells(page) == []
        assert _text(page, "am-build-body").strip() == (
            "Item build needs the live game feed."
        )
        assert _text(page, "am-map-body").strip() == (
            "Map intel needs the live game feed."
        )
        view = _text(page, "view-active-match")
        for needle in _LOL_ONLY:
            assert needle not in view, f"League text {needle!r} in live view"
        # Whole visible page, not just the Active Match view. "Drake spawns"
        # is the fallback's own guard (the League path paints coach.action into
        # CALL); the callout / lead needles are a backstop for the older
        # live-directive gate (panels/callouts.js) and the live view pin.
        body = page.evaluate("() => document.body.innerText")
        for needle in _SR_IMPERATIVES:
            assert needle not in body, f"SR imperative {needle!r} visible mid-game"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def _next_text(page) -> dict:
    """#next subtree text via textContent (the DOM, hidden or not) plus the
    #nx-next headline alone."""
    return page.evaluate(
        "() => ({all: document.getElementById('next').textContent,"
        " head: document.getElementById('nx-next').textContent})"
    )


def test_real_client_row_next_panel_holds_no_sr_imperative(
    mock_server, pw_browser
):
    """RM-896 (next.js half). The live view pin hides #next, so the visible
    page was clean while #nx-next still HELD "Drake spawns 5:00 - set up
    vision" (next.js aftergame branch: advice_headline || next || action).
    textContent, not innerText: the guarantee must not rest on view routing.
    next.js now runs the coach payload through the B4 client mirror
    (live_directive_gate.withoutLiveDirectives) while a game is live."""
    ctx, page, errors = _open(
        mock_server, pw_browser, _load("tft_live_s134_client")
    )
    try:
        _wait_fallback(page, "game")
        _wait_state_ticks(page, 1)
        nx = _next_text(page)
        for needle in _SR_IMPERATIVES:
            assert needle not in nx["all"], (
                f"SR imperative {needle!r} held in #next mid-game"
            )
        assert nx["head"] == "-"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_client_row_after_the_game_keeps_the_next_headline(
    mock_server, pw_browser
):
    """Positive control: the same row with the LCU at EndOfGame is not a live
    game, so the post-game NEXT surface still paints coach.action - the gate
    is phase-driven, not a blanket strip."""
    row = _load("tft_live_s134_client")
    row["lcu"]["phase"] = "EndOfGame"
    ctx, page, errors = _open(mock_server, pw_browser, row)
    try:
        page.wait_for_function(
            "() => (document.getElementById('nx-next')?.textContent || '')"
            ".includes('Drake spawns')",
            timeout=_LIVE_TICK_MS,
        )
        _wait_state_ticks(page, 2)
        assert _next_text(page)["head"] == "Drake spawns 5:00 - set up vision"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_lcu_phase_blink_holds_then_sr_game_rebuilds_league_panes(
    mock_server, pw_browser
):
    """A blank LCU phase mid-game (the LCU agent drops a stale snapshot) holds
    the TFT fallback for the same mode; the next SR game in the SAME page (no
    reload) gets the League panes back with no TFT text left behind."""
    tft = _load("tft_live_s134")
    ctx, page, errors = _open(mock_server, pw_browser, tft)
    try:
        _wait_fallback(page, "tft")

        blink = copy.deepcopy(tft)
        blink["lcu"]["phase"] = ""
        mock_server._store["data"] = blink
        _wait_state_ticks(page, 2)
        assert page.locator(_FALLBACK_HEAD).get_attribute(
            "data-am-fallback"
        ) == "tft", "LCU phase blink flipped the live TFT panes"
        assert _text(page, "am-map-body").strip() == "No map intel in TFT."

        sr = _load("sr")
        sr["lcu"] = copy.deepcopy(tft["lcu"])
        mock_server._store["data"] = sr
        page.wait_for_function(
            "!!document.getElementById('am-map-status')"
            " && document.body.dataset.mode === 'sr'",
            timeout=_LIVE_TICK_MS,
        )
        assert page.locator(_FALLBACK_HEAD).count() == 0
        view = _text(page, "view-active-match")
        for needle in ("No map intel in TFT.", "No League item build in TFT.",
                       "TFT LIVE DATA"):
            assert needle not in view, f"TFT text {needle!r} left in SR game"
        assert _text(page, "am-build-body").strip(), "SR build pane left blank"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# RM-898: every value #nx-next ever holds, from the first DOM paint on.
_NX_WRITE_LOG = """
window.__nxLog = [];
document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('nx-next');
  if (!el) return;
  window.__nxLog.push(el.textContent);
  new MutationObserver(() => window.__nxLog.push(el.textContent))
    .observe(el, {childList: true, characterData: true, subtree: true});
});
"""

# RM-898: make the HTTP fallback (pollIfStale) the ONLY state.latest.lcu
# writer, then log what #nx-next holds right after each fallback tick renders.
#   - No EventSource: setupStateStream returns, so no SSE tick.
#   - pollLcu (the independent LCU poller) gets "{}" back, so it never calls
#     handleLcuEnvelope and cannot refresh the cache between fallback ticks;
#     without this the defect reproduces only when pollLcu happens to lose
#     the race. The caller is told apart by its function name on the stack.
#   - A pollIfStale /api/state response logs {phase, head} in a setTimeout 0
#     queued when its json() resolves, which runs after the handler's
#     synchronous render (onState + handleLcuEnvelope) completes.
_FALLBACK_ONLY_TICK_LOG = """
(() => {
  window.EventSource = undefined;
  window.__ticks = [];
  const orig = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : ((input && input.url) || '');
    if (!url.split('?')[0].endsWith('/api/state')) return orig(input, init);
    const stack = new Error().stack || '';
    if (stack.indexOf('pollLcu') !== -1) {
      return Promise.resolve(new Response('{}', {
        status: 200, headers: {'Content-Type': 'application/json'}}));
    }
    if (stack.indexOf('pollIfStale') === -1) return orig(input, init);
    return orig(input, init).then((resp) => {
      const json = resp.json.bind(resp);
      resp.json = () => json().then((d) => {
        setTimeout(() => {
          const el = document.getElementById('nx-next');
          window.__ticks.push({
            phase: (d && d.lcu && d.lcu.phase) || '',
            head: el ? el.textContent : null,
          });
        }, 0);
        return d;
      });
      return resp;
    });
  };
})();
"""


def test_first_sse_tick_of_a_live_page_paints_no_sr_imperative(
    mock_server, pw_browser
):
    """RM-898, SSE site. The page loads straight into the live client row
    (lcu.phase InProgress, no :2999 feed). The first render is the SSE event;
    before the fix onState ran before handleLcuEnvelope cached state.latest.lcu,
    so the B4 mirror in next.js saw no live game and #nx-next held "Drake
    spawns 5:00 - set up vision" until the next tick. A MutationObserver
    records every value #nx-next ever holds; none may be an SR imperative."""
    ctx, page, errors = _open(
        mock_server, pw_browser, _load("tft_live_s134_client"),
        init_scripts=(_NX_WRITE_LOG,),
    )
    try:
        _wait_fallback(page, "game")
        _wait_state_ticks(page, 1)
        log = page.evaluate("window.__nxLog")
        assert log and log[0] == "-", f"observer not installed: {log[:3]}"
        for value in log:
            for needle in _SR_IMPERATIVES:
                assert needle not in value, (
                    f"#nx-next held {value!r} on a live page: {log}"
                )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_first_fallback_tick_after_champ_select_paints_no_sr_imperative(
    mock_server, pw_browser
):
    """RM-898, HTTP-fallback site. ChampSelect is pre-game, so the coach
    headline paints there (the positive control below the flip). On the
    FIRST fallback tick that serves lcu.phase InProgress the B4 mirror must
    already see the live game: before the fix state.latest.lcu still held
    the ChampSelect snapshot when onState ran, and #nx-next kept "Drake
    spawns 5:00 - set up vision" for one more tick."""
    pre = _load("tft_live_s134_client")
    pre["lcu"]["phase"] = "ChampSelect"
    ctx, page, errors = _open(
        mock_server, pw_browser, pre, init_scripts=(_FALLBACK_ONLY_TICK_LOG,),
    )
    try:
        page.wait_for_function(
            "() => (window.__ticks || []).some(t => t.phase === 'ChampSelect'"
            " && t.head.includes('Drake spawns'))",
            timeout=_LIVE_TICK_MS,
        )
        mock_server._store["data"] = _load("tft_live_s134_client")
        page.wait_for_function(
            "() => (window.__ticks || []).filter("
            "t => t.phase === 'InProgress').length >= 2",
            timeout=_LIVE_TICK_MS,
        )
        live = [t for t in page.evaluate("window.__ticks")
                if t["phase"] == "InProgress"]
        for needle in _SR_IMPERATIVES:
            assert needle not in live[0]["head"], (
                f"first InProgress tick held {live[0]['head']!r}"
            )
        assert [t["head"] for t in live[:2]] == ["-", "-"]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
