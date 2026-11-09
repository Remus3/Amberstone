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


# The static index.html head of the BUILD pane. The TFT fallback renames it
# BOARD (that pane holds the board in TFT) and the feed path puts BUILD back
# (RM-939; _amRenderLiveFallback / renderActiveMatchView in
# web/js/panels/active_match.js).
_BUILD_HEAD = "#view-active-match .am-pane-build .am-pane-head"


def _build_head(page) -> list:
    """[textContent, visible] of the BUILD pane head on the dashboard."""
    head = page.locator(_BUILD_HEAD)
    return [head.text_content(), head.is_visible()]


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
        assert _text(page, "am-build-body").strip() == (
            "UNITS\nUnits appear after the TFT client writes its first round."
        )
        assert _build_head(page) == ["BOARD", True]
        assert _text(page, "am-map-body").strip() == (
            "LOBBY\nLobby placements and HP appear after the first round."
        )

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
        # Mode not detected is not TFT: the pane keeps its BUILD head.
        assert _build_head(page) == ["BUILD", True]
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


# S144-U-265: the RM-896 NEXT-panel pair (the live row held no SR imperative
# in the hidden NEXT headline; the EndOfGame row kept it) is retired with the
# never-rendered NEXT panel and its module. The RIGHT NOW pair below pins the
# same B4 mirror on the kept sink; tests/snapshot_panels/
# test_next_panel_retired.py pins that the panel is not served.


def _right_now_text(page) -> dict:
    """#right-now subtree text via textContent (the DOM, hidden or not) plus
    the coach-field rows right_now.js paints."""
    return page.evaluate(
        "() => { const t = (id) => document.getElementById(id).textContent;"
        " return {all: t('right-now'), action: t('rn-action'),"
        " immediate: t('rn-immediate'), risk: t('rn-risk'),"
        " fight: t('rn-fight-rule')}; }"
    )


# The real client row's live-suppressed coach fields that are not SR
# imperatives by name: coach.fight_rule and coach.risk ("MEDIUM").
_RN_SUPPRESSED = _SR_IMPERATIVES + ("FAIR FIGHT", "coinflips")


def test_real_client_row_right_now_holds_no_sr_imperative(
    mock_server, pw_browser
):
    """RM-896 (right_now.js half). Same real row the retired NEXT test used: the
    live view pin hides #right-now, but #rn-action and #rn-immediate held
    "Drake spawns 5:00 - set up vision" and #rn-fight-rule the FAIR FIGHT
    rule in the DOM. textContent, not innerText: the guarantee must not rest
    on view routing. right_now.js now reads the coach payload through the B4
    client mirror (live_directive_gate.withoutLiveDirectives) while a game is
    live, so every row it paints from a suppressed field shows the no-data
    "-"."""
    ctx, page, errors = _open(
        mock_server, pw_browser, _load("tft_live_s134_client")
    )
    try:
        _wait_fallback(page, "game")
        _wait_state_ticks(page, 1)
        rn = _right_now_text(page)
        for needle in _RN_SUPPRESSED:
            assert needle not in rn["all"], (
                f"live-suppressed text {needle!r} held in #right-now mid-game"
            )
        assert rn["action"] == "-"
        assert rn["risk"] == "-"
        assert rn["fight"] == "-"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_client_row_after_the_game_keeps_the_right_now_headline(
    mock_server, pw_browser
):
    """Positive control: the same row at EndOfGame is not a live game, so
    RIGHT NOW still paints coach.action, immediate, risk and fight_rule - the
    gate is phase-driven, not a blanket strip, and the live test above is not
    passing because right_now.js never renders this row."""
    row = _load("tft_live_s134_client")
    row["lcu"]["phase"] = "EndOfGame"
    ctx, page, errors = _open(mock_server, pw_browser, row)
    try:
        page.wait_for_function(
            "() => (document.getElementById('rn-action')?.textContent || '')"
            ".includes('Drake spawns')",
            timeout=_LIVE_TICK_MS,
        )
        _wait_state_ticks(page, 2)
        rn = _right_now_text(page)
        assert rn["action"].endswith("Drake spawns 5:00 - set up vision")
        assert rn["immediate"] == "Drake spawns 5:00 - set up vision"
        assert rn["risk"] == "MEDIUM"
        assert rn["fight"].startswith("FAIR FIGHT")
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
        assert _text(page, "am-map-body").strip() == (
            "LOBBY\nLobby placements and HP appear after the first round."
        )
        assert _build_head(page)[0] == "BOARD"

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
        for needle in ("Lobby placements and HP appear after the first round.",
                       "Units appear after the TFT client writes its first round.",
                       "TFT LIVE DATA"):
            assert needle not in view, f"TFT text {needle!r} left in SR game"
        assert _text(page, "am-build-body").strip(), "SR build pane left blank"
        assert _build_head(page) == ["BUILD", True], "TFT BOARD head left in SR game"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# RM-898: every value #rn-immediate ever holds, from the first DOM paint on.
# (S144-U-265: the probe read the retired NEXT headline; RIGHT NOW reads the
# coach through the same B4 mirror, so the ordering fix is pinned there.)
_RN_WRITE_LOG = """
window.__rnLog = [];
document.addEventListener('DOMContentLoaded', () => {
  const el = document.getElementById('rn-immediate');
  if (!el) return;
  window.__rnLog.push(el.textContent);
  new MutationObserver(() => window.__rnLog.push(el.textContent))
    .observe(el, {childList: true, characterData: true, subtree: true});
});
"""

# RM-898: make the HTTP fallback (pollIfStale) the ONLY state.latest.lcu
# writer, then log what #rn-immediate holds right after each fallback tick
# renders.
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
          const el = document.getElementById('rn-immediate');
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


# RM-940: make the SSE event the ONLY state.latest.lcu writer before the
# first render, so the SSE-site test below cannot pass by a race.
#   - pollLcu gets "{}" back (caller told apart by its name on the stack, as in
#     _FALLBACK_ONLY_TICK_LOG). It fires once on load and then every 2 s, and
#     lastSseTs starts undefined, so neither call is suppressed before the
#     first SSE event; had one won, it would cache lcu InProgress via
#     handleLcuEnvelope and hide a regressed SSE site.
#   - pollIfStale stays live (its 4 s staleness floor keeps it off the first
#     render, and its responses are what _wait_state_ticks counts), but the
#     time of its first /api/state fetch is logged against the first SSE
#     message, so "the first render is the SSE event" is asserted, not assumed.
_SSE_FIRST_POLL_LCU_OFF = """
(() => {
  window.__sseAt = null;
  window.__httpStateAt = null;
  const OrigES = window.EventSource;
  if (OrigES) {
    const Wrapped = function (url, cfg) {
      const es = new OrigES(url, cfg);
      es.addEventListener('message', () => {
        if (window.__sseAt === null) window.__sseAt = performance.now();
      });
      return es;
    };
    Wrapped.prototype = OrigES.prototype;
    window.EventSource = Wrapped;
  }
  const orig = window.fetch.bind(window);
  window.fetch = function (input, init) {
    const url = typeof input === 'string' ? input : ((input && input.url) || '');
    if (!url.split('?')[0].endsWith('/api/state')) return orig(input, init);
    const stack = new Error().stack || '';
    if (stack.indexOf('pollLcu') !== -1) {
      return Promise.resolve(new Response('{}', {
        status: 200, headers: {'Content-Type': 'application/json'}}));
    }
    if (window.__httpStateAt === null) window.__httpStateAt = performance.now();
    return orig(input, init);
  };
})();
"""


def test_first_sse_tick_of_a_live_page_paints_no_sr_imperative(
    mock_server, pw_browser
):
    """RM-898, SSE site. The page loads straight into the live client row
    (lcu.phase InProgress, no :2999 feed). The first render is the SSE event;
    before the fix onState ran before handleLcuEnvelope cached state.latest.lcu,
    so the B4 mirror saw no live game and the coach sinks held "Drake
    spawns 5:00 - set up vision" until the next tick. A MutationObserver
    records every value #rn-immediate ever holds; none may be an SR
    imperative.
    pollLcu is neutralised and the SSE event is checked to land before any
    HTTP /api/state fetch (RM-940), so no poller can pre-cache lcu."""
    ctx, page, errors = _open(
        mock_server, pw_browser, _load("tft_live_s134_client"),
        init_scripts=(_RN_WRITE_LOG, _SSE_FIRST_POLL_LCU_OFF),
    )
    try:
        _wait_fallback(page, "game")
        _wait_state_ticks(page, 1)
        order = page.evaluate("[window.__sseAt, window.__httpStateAt]")
        assert order[0] is not None, "no SSE message reached the page"
        assert order[1] is None or order[0] < order[1], (
            f"an HTTP /api/state fetch preceded the first SSE event: {order}"
        )
        log = page.evaluate("window.__rnLog")
        assert log and log[0] == "awaiting coach output...", (
            f"observer not installed: {log[:3]}")
        for value in log:
            for needle in _SR_IMPERATIVES:
                assert needle not in value, (
                    f"#rn-immediate held {value!r} on a live page: {log}"
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
    the ChampSelect snapshot when onState ran, and the coach sinks (then
    the NEXT headline, retired S144-U-265; now #rn-immediate) kept "Drake
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
        # #rn-immediate falls back to coach.pregame, which the B4 mirror
        # does not blank (it is not a live imperative): both live ticks
        # paint it, so the render ran with the live game already seen.
        pregame = _load("tft_live_s134_client")["coach"]["pregame"]
        assert [t["head"] for t in live[:2]] == [pregame, pregame]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_eliminated_player_strip_reads_out(mock_server, pw_browser):
    """RM-942: the real elimination moment (tft_qa run 20261025-104400,
    states.jsonl line 73: coach hp -9 at standing 8, stage 5-2) paints HP "OUT"
    in the fixed strip, undimmed, beside the placement - never the no-data "-"
    and never the coach's stale health (10)."""
    data = copy.deepcopy(_load("tft_live_s134"))
    data["coach"].update({"hp": -9, "health": 10, "standing": 8, "stage_round": "5-2"})
    ctx, page, errors = _open(mock_server, pw_browser, data)
    try:
        _wait_fallback(page, "tft")
        page.wait_for_function(
            "() => [...document.querySelectorAll('#am-call-body .am-tft-stat-value')]"
            ".some(v => v.textContent === 'OUT')",
            timeout=_LIVE_TICK_MS,
        )
        assert _stat_cells(page) == [
            ["STAGE", "5-2", False], ["LEVEL", "-", True],
            ["HP", "OUT", False], ["GOLD", "-", True],
        ]
        assert _text(page, "am-sub") == "TFT - stage 5-2 - 8th of 8 - phase InProgress"
        clipped = page.evaluate(
            "() => [...document.querySelectorAll('#am-call-body .am-tft-stat-value')]"
            ".filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent)")
        assert clipped == [], f"clipped text: {clipped}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_placeholder_hp_beside_lobby_you_row_is_not_out(mock_server, pw_browser):
    """RM-943: OUT pairs the hp read with the placement from the SAME source.
    A game-start placeholder (hp / standing -1, QA N10) beside a lobby you-row
    at 3rd with 64 HP paints the no-data "-" (dimmed), never "OUT"; the you-row
    still supplies the placement in the sub line."""
    data = copy.deepcopy(_load("tft_live_s134"))
    data["coach"].update({
        "hp": -1, "standing": -1, "stage_round": "3-2",
        "tft_players": [
            {"standing": 1, "health": 70}, {"standing": 3, "health": 64, "you": True},
            {"standing": 8, "health": 0},
        ],
    })
    ctx, page, errors = _open(mock_server, pw_browser, data)
    try:
        _wait_fallback(page, "tft")
        page.wait_for_function(
            "() => (document.getElementById('am-sub') || {}).textContent"
            " === 'TFT - stage 3-2 - 3rd of 3 - phase InProgress'",
            timeout=_LIVE_TICK_MS,
        )
        assert _stat_cells(page) == [
            ["STAGE", "3-2", False], ["LEVEL", "-", True],
            ["HP", "-", True], ["GOLD", "-", True],
        ]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_start_sentinel_hp_falls_through_to_coach_health(mock_server, pw_browser):
    """RM-947: the real game-start placeholder row (tft_qa runs
    20261025-104400 and 20261025-131926, states.jsonl row 3: coach hp -1 /
    standing -1 with health 100 at stage 1-2, between a 1-1 row and a 1-3 row
    that both paint HP 100) paints HP "100", undimmed - not the no-data "-" -
    the same text the overlay vitals show for that row."""
    data = copy.deepcopy(_load("tft_live_s134"))
    data["coach"].update({
        "hp": -1, "health": 100, "standing": -1,
        "stage_round": "1-2", "level": 1, "gold": 0,
    })
    ctx, page, errors = _open(mock_server, pw_browser, data)
    try:
        _wait_fallback(page, "tft")
        page.wait_for_function(
            "() => (document.getElementById('am-sub') || {}).textContent"
            " === 'TFT - stage 1-2 - phase InProgress'",
            timeout=_LIVE_TICK_MS,
        )
        assert _stat_cells(page) == [
            ["STAGE", "1-2", False], ["LEVEL", "1", False],
            ["HP", "100", False], ["GOLD", "0", False],
        ]
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# [hp text, is-you, data-band, is-low] per dashboard lobby row, in DOM order.
_LOBBY_BANDS_JS = (
    "() => Array.from(document.querySelectorAll("
    "'#am-map-body .am-tft-lob-row')).map(r => {"
    " const f = r.querySelector('.am-tft-lob-fill');"
    " return [r.querySelector('.am-tft-lob-hp').textContent,"
    " r.classList.contains('is-you'), f.dataset.band || '',"
    " f.classList.contains('is-low')]; })"
)

# The overlay vitals band for the same coach payload, computed in the same page
# by the overlay's own module (web/js/lib/overlay_tft.js tftOverlayModel).
_OVERLAY_BAND_JS = (
    "(coach) => import('/js/lib/overlay_tft.js').then(m =>"
    " m.tftOverlayModel({ mode_key: 'tft', liveclient: {}, coach }).vitals[0].band)"
)


def test_lobby_hp_bands_match_the_overlay_vitals(mock_server, pw_browser):
    """RM-948: one set of TFT HP bands on both screens. Real row 77 of tft_qa
    run 20261025-162857 (stage 4-6, you 5th at 36 HP; lobby 70 / 64 / 60 / 52 /
    36 / 28 / 25 / 4). The dashboard lobby used to go red at <= 25 (the 25 row
    red, the 36 you-row plain) while the overlay vitals read 36 as amber "low".
    Now every bar carries the overlay's band (crit <= 20, low <= 40), the red
    is-low fill is the crit band only, and the you-row's band is the band the
    overlay vitals paint for that same payload."""
    data = copy.deepcopy(_load("tft_live_s134"))
    coach = {
        "hp": 36, "standing": 5, "stage_round": "4-6",
        "tft_players": [
            {"standing": s, "health": h, "you": s == 5}
            for s, h in zip(range(1, 9), (70, 64, 60, 52, 36, 28, 25, 4))
        ],
    }
    data["coach"].update(coach)
    ctx, page, errors = _open(mock_server, pw_browser, data)
    try:
        _wait_fallback(page, "tft")
        page.wait_for_function(
            "document.querySelectorAll('#am-map-body .am-tft-lob-row').length === 8",
            timeout=_LIVE_TICK_MS,
        )
        assert page.evaluate(_LOBBY_BANDS_JS) == [
            ["70", False, "", False], ["64", False, "", False],
            ["60", False, "", False], ["52", False, "", False],
            ["36", True, "low", False], ["28", False, "low", False],
            ["25", False, "low", False], ["4", False, "crit", True],
        ]
        overlay_band = page.evaluate(_OVERLAY_BAND_JS, data["coach"])
        assert overlay_band == "low"
        you = [r for r in page.evaluate(_LOBBY_BANDS_JS) if r[1]]
        assert you[0][2] == overlay_band
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


# [label, value, data-band] per .am-tft-stat cell, in DOM order.
_STAT_BANDS_JS = (
    "() => Array.from(document.querySelectorAll("
    "'#am-call-body .am-tft-stat')).map(c => ["
    "c.querySelector('.am-tft-stat-label').textContent,"
    "c.querySelector('.am-tft-stat-value').textContent,"
    "c.dataset.band || ''])"
)


def test_strip_hp_cell_band_matches_the_overlay_vitals(mock_server, pw_browser):
    """RM-949: the fixed strip's HP cell carries the overlay vitals band for
    the same payload. Real tft_qa rows, painted as successive ticks of one
    page (states.jsonl line numbers, 1-based): run 20261025-162857 line 77
    (stage 4-6, 5th at 36 HP) reads "low" on the overlay vitals, its line 95
    (stage 5-5, 5th at 13 HP) reads "crit", and the elimination line 73 of run
    20261025-104400 (hp -9 / health 10 at 8th,
    stage 5-2) reads OUT with no band - out is not the crit pop-out. Only the
    HP cell carries a band, and the band follows the HP across ticks (the
    strip's repaint signature covers it)."""
    data = copy.deepcopy(_load("tft_live_s134"))
    data["coach"].update({"hp": 36, "standing": 5, "stage_round": "4-6"})
    ctx, page, errors = _open(mock_server, pw_browser, data)
    try:
        _wait_fallback(page, "tft")
        page.wait_for_function(
            "() => [...document.querySelectorAll('#am-call-body .am-tft-stat-value')]"
            ".some(v => v.textContent === '36')",
            timeout=_LIVE_TICK_MS,
        )
        assert page.evaluate(_STAT_BANDS_JS) == [
            ["STAGE", "4-6", ""], ["LEVEL", "-", ""],
            ["HP", "36", "low"], ["GOLD", "-", ""],
        ]
        assert page.evaluate(_OVERLAY_BAND_JS, data["coach"]) == "low"

        for coach, hp_text, band in (
            ({"hp": 13, "health": 26, "standing": 5, "stage_round": "5-5"}, "13", "crit"),
            ({"hp": -9, "health": 10, "standing": 8, "stage_round": "5-2"}, "OUT", ""),
        ):
            data["coach"].update(coach)
            mock_server._store["data"] = data
            page.wait_for_function(
                "(t) => [...document.querySelectorAll('#am-call-body .am-tft-stat-value')]"
                ".some(v => v.textContent === t)",
                arg=hp_text,
                timeout=_LIVE_TICK_MS,
            )
            cells = page.evaluate(_STAT_BANDS_JS)
            assert cells[2] == ["HP", hp_text, band]
            assert [c[2] for c in cells[:2] + cells[3:]] == ["", "", ""]
            assert page.evaluate(_OVERLAY_BAND_JS, data["coach"]) == band
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
