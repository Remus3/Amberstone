"""
tests/snapshot_panels/test_champ_select_enemy_wr_slot_fetch_hardening.py
RM-1200 (s144 uiux): the SR champ-select enemy win-rate slot fetch
(web/js/panels/champ_select.js _csvWrSlotFetch, the leading
.csv-enemy-wr-slot on each enemy cell) is hardened in two ways.

(a) A request that never answers settles as FAILED after
    _CSV_WR_TIMEOUT_MS. Before, the cache entry stayed pending forever:
    the slot stayed EMPTY for the whole champ select and that champion
    was never asked again (every re-render saw pending and returned).
(b) A refetch that fails after the 60 s success TTL keeps the last good
    win rate (its title says the refresh failed) instead of overwriting
    it with "--" for the failure back-off.

Routing (synthetic numbers, RM-906): 122 -> 62% (ok), every other
enemy -> sample_n 0, except where a test says otherwise. Time is moved
with Playwright's clock (installed before navigation, so Date.now and
setTimeout both move); re-renders are forced by clearing the section's
idempotent-render signature (data-csv-sig), which is what a real
champ-select state change does.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_OK = {"ok": True, "sample_n": 8, "wr_pct": 62, "wins": 5, "losses": 3,
       "days": 30, "champ_name": "Darius"}
_EMPTY = {"ok": True, "sample_n": 0, "wr_pct": 0, "wins": 0, "losses": 0,
          "days": 30}

_SLOTS = """() => Object.fromEntries([...document.querySelectorAll(
    '#view-champ-select #csv-enemies-list .csv-enemy-wr-slot')]
  .filter((e) => e.dataset.champId)
  .map((e) => [e.dataset.champId,
               {text: e.textContent.trim(), cls: e.className,
                title: e.title || ''}]))"""

# Forces one re-render through the SAME module instance main.js
# imported (a real champ-select state change does the same).
_RERENDER = """async () => {
  const mod = await import('/js/panels/champ_select.js');
  const fx = await (await fetch(
    mod.csMockFixtureUrl(location.search), {cache: 'no-store'})).json();
  const lcu = {phase: fx.phase || 'ChampSelect',
               champ_select: fx.champ_select, config: fx.config || {}};
  delete document.getElementById('view-champ-select').dataset.csvSig;
  mod.renderChampSelectView(lcu);
}"""


def _open(mock_server, pw_browser, route_fn):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.clock.install()
    page.add_init_script(_WS_STUB)
    page.route("**/api/personal-vs*", route_fn)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/?ui_mock=1&mode=sr#champ-select",
              wait_until="domcontentloaded", timeout=15_000)
    return ctx, page, errors


def _cid(url):
    return int(url.split("champ_id=")[1].split("&")[0])


def _wait_slots(page, cond_js, timeout=10_000):
    page.wait_for_function(
        "() => { const s = (" + _SLOTS + ")(); return (" + cond_js + ")(s); }",
        timeout=timeout,
    )
    return page.evaluate(_SLOTS)


@pytest.fixture(scope="module")
def hung(mock_server, pw_browser):
    """412 never answers; every other enemy answers at once."""
    hits: dict[int, int] = {}
    parked = []

    def _route(route):
        cid = _cid(route.request.url)
        hits[cid] = hits.get(cid, 0) + 1
        if cid == 412:
            parked.append(route)  # never fulfilled: a hung request
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_OK if cid == 122 else _EMPTY))

    ctx, page, errors = _open(mock_server, pw_browser, _route)
    try:
        # Every answering enemy painted; the hung one is still empty.
        before = _wait_slots(
            page,
            "(s) => Object.keys(s).length === 5 && s['122'].text === '62%'"
            " && Object.entries(s).filter(([k]) => k !== '412')"
            ".every(([, v]) => v.text)")
        first = dict(hits)
        page.clock.run_for(9_000)
        timed_out = None
        try:
            timed_out = _wait_slots(page, "(s) => s['412'].text === '--'",
                                    timeout=3_000)
        except Exception:  # noqa: BLE001 - recorded, asserted below
            timed_out = page.evaluate(_SLOTS)
        # Past the failure back-off, a re-render asks the hung one again.
        page.clock.run_for(16_000)
        page.evaluate(_RERENDER)
        page.wait_for_timeout(300)
        retried = dict(hits)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return {"before": before, "first": first, "timed_out": timed_out,
            "retried": retried}


def test_hung_request_starts_pending(hung):
    # Positive control: the slot really was waiting on the hung request.
    assert hung["first"].get(412) == 1, hung["first"]
    assert hung["before"]["412"]["text"] == "", hung["before"]


def test_hung_request_settles_as_failed_after_timeout(hung):
    slot = hung["timed_out"]["412"]
    assert slot["text"] == "--", (
        f"a /api/personal-vs request that never answers left the slot "
        f"empty past the timeout: {slot}")
    assert "is-new" in slot["cls"].split(), slot


def test_hung_champion_is_retried_after_the_backoff(hung):
    assert hung["retried"].get(412) == 2, (
        f"a hung request blocked every later retry: {hung['retried']}")
    # The good answer was not refetched inside its 60 s TTL.
    assert hung["retried"].get(122) == hung["first"].get(122), hung


@pytest.fixture(scope="module")
def refetch_fails(mock_server, pw_browser):
    """122 answers 62% once, then every refetch is a 503."""
    hits: dict[int, int] = {}

    def _route(route):
        cid = _cid(route.request.url)
        hits[cid] = hits.get(cid, 0) + 1
        if cid == 122 and hits[cid] > 1:
            route.fulfill(status=503, content_type="application/json",
                          body=json.dumps({"ok": False,
                                           "error": "rewind_history.db missing"}))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_OK if cid == 122 else _EMPTY))

    ctx, page, errors = _open(mock_server, pw_browser, _route)
    try:
        first = _wait_slots(
            page, "(s) => Object.keys(s).length === 5"
                  " && Object.values(s).every((v) => v.text)")
        reads = []
        # Past the 60 s success TTL: the refetch fails. Then past the
        # 15 s failure back-off: it fails again.
        for step in (70_000, 20_000):
            page.clock.run_for(step)
            page.evaluate(_RERENDER)
            page.wait_for_timeout(300)
            reads.append(page.evaluate(_SLOTS))
        refetches = hits.get(122, 0)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return {"first": first, "reads": reads, "hits_122": refetches}


def test_refetch_really_failed(refetch_fails):
    # Positive control: the first answer was good and both refetches ran.
    assert refetch_fails["first"]["122"]["text"] == "62%", refetch_fails
    assert refetch_fails["hits_122"] == 3, refetch_fails


def test_failed_refetch_keeps_last_good_win_rate(refetch_fails):
    for r in refetch_fails["reads"]:
        slot = r["122"]
        assert slot["text"] == "62%", (
            f"a failed refetch overwrote the last good win rate: {slot}")
        assert "is-new" not in slot["cls"].split(), slot
        assert "refresh failed" in slot["title"], slot
        # The kept title still carries the record it is showing.
        assert "5W 3L" in slot["title"], slot


def test_a_never_good_failure_still_reads_dashes(hung):
    # The keep-last-good path must not invent a value: a champion whose
    # only answer was a failure still reads "--" with the no-games title.
    slot = hung["timed_out"]["412"]
    assert "no games" in slot["title"], slot
    assert "refresh failed" not in slot["title"], slot
