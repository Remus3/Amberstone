"""
tests/snapshot_panels/test_champ_select_enemy_wr_slot_negative_cache.py
RM-1199 (s144 uiux): the SR champ-select enemy win-rate slot
(web/js/panels/champ_select.js _csvWrSlotFetch / _csvWrSlotApply, the
leading .csv-enemy-wr-slot on each enemy cell) caches a FAILED
/api/personal-vs answer too, and a re-rendered slot never paints empty
while a cached answer exists.

Before: the catch path stored {payload: null} but the cache-hit check
needed a truthy payload, so after a 503 (the real routes_personal_vs
answer when rewind_history.db is missing) or a 500 every _csvRenderTeam
re-render re-requested the route, and each freshly built slot painted
EMPTY (no text) until that retry failed again. The RM-1198 contrast
guard raced on exactly this.

After: a failure is negative-cached for a short back-off
(_CSV_WR_FAIL_TTL_MS), and once any answer has settled a rebuilt slot
paints it at once, including while an expired entry is being refetched
(stale-while-revalidate), so the "--" or the win rate never blinks out.

Routing (synthetic numbers, RM-906): 122 -> 62% (ok), 412 -> 503,
every other enemy -> sample_n 0. Re-renders are forced by clearing the
section's idempotent-render signature (data-csv-sig), which is what a
real champ-select state change does; time is advanced by skewing
Date.now inside the page.
"""
import json

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_OK = {"ok": True, "sample_n": 8, "wr_pct": 62, "wins": 5, "losses": 3,
       "days": 30, "champ_name": "Darius"}
_EMPTY = {"ok": True, "sample_n": 0, "wr_pct": 0, "wins": 0, "losses": 0,
          "days": 30}

# Runs in the page after the first paint settled. Re-renders the view
# through the SAME module instance main.js imported, reads every slot
# synchronously right after each render (before any fetch can resolve),
# and returns the reads.
_RERENDER = """async ({skews}) => {
  const mod = await import('/js/panels/champ_select.js');
  const fx = await (await fetch(
    mod.csMockFixtureUrl(location.search), {cache: 'no-store'})).json();
  const lcu = {phase: fx.phase || 'ChampSelect',
               champ_select: fx.champ_select, config: fx.config || {}};
  const realNow = Date.now.bind(Date);
  let skew = 0;
  Date.now = () => realNow() + skew;
  const read = () => Object.fromEntries([...document.querySelectorAll(
      '#view-champ-select #csv-enemies-list .csv-enemy-wr-slot')]
    .filter((e) => e.dataset.champId)
    .map((e) => [e.dataset.champId, e.textContent.trim()]));
  const section = document.getElementById('view-champ-select');
  const out = [];
  for (const s of skews) {
    skew = s;
    delete section.dataset.csvSig;
    mod.renderChampSelectView(lcu);
    out.push({skew: s, slots: read()});
    // Let any refetch fired by this render land before the next one.
    await new Promise((r) => setTimeout(r, 300));
    out.push({skew: s, settled: true, slots: read()});
  }
  return out;
}"""


def _run(mock_server, pw_browser, skews):
    mock_server._store["data"] = {}
    hits: dict[int, int] = {}

    def _route(route):
        url = route.request.url
        cid = int(url.split("champ_id=")[1].split("&")[0])
        hits[cid] = hits.get(cid, 0) + 1
        if cid == 412:
            route.fulfill(status=503, content_type="application/json",
                          body=json.dumps({"ok": False,
                                           "error": "rewind_history.db missing"}))
            return
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(_OK if cid == 122 else _EMPTY))

    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    page.route("**/api/personal-vs*", _route)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=sr#champ-select",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            """() => {
              const s = [...document.querySelectorAll(
                '#view-champ-select #csv-enemies-list .csv-enemy-wr-slot')];
              return s.length === 5 && s.every((e) => e.textContent.trim());
            }""",
            timeout=10_000,
        )
        first = dict(hits)
        reads = page.evaluate(_RERENDER, {"skews": skews})
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return first, dict(hits), reads


@pytest.fixture(scope="module")
def within_backoff(mock_server, pw_browser):
    # Three forced re-renders, all inside the failure back-off.
    return _run(mock_server, pw_browser, [0, 0, 0])


def test_first_paint_asks_each_enemy_once(within_backoff):
    first, _, _ = within_backoff
    assert first.get(412) == 1 and first.get(122) == 1, first


def test_a_failed_answer_is_not_refetched_inside_the_backoff(within_backoff):
    first, after, _ = within_backoff
    # Positive control: the success was cached at HEAD too, so a zero
    # here proves the re-renders reused main.js's module instance.
    assert after.get(122) == first.get(122), (first, after)
    assert after.get(412) == first.get(412), (
        f"failed /api/personal-vs re-requested on every re-render: "
        f"{first.get(412)} -> {after.get(412)}")


def test_a_failed_slot_never_paints_empty_on_rerender(within_backoff):
    _, _, reads = within_backoff
    for r in reads:
        assert r["slots"].get("412") == "--", r
        assert r["slots"].get("122") == "62%", r


@pytest.fixture(scope="module")
def past_ttls(mock_server, pw_browser):
    # One render past the failure back-off (but inside the 60 s success
    # TTL), then one past the success TTL.
    return _run(mock_server, pw_browser, [20_000, 70_000])


def test_failure_is_retried_after_the_backoff(past_ttls):
    first, after, _ = past_ttls
    # skew 20 s retries the failure once, skew 70 s once more.
    assert after.get(412) == first.get(412) + 2, (first, after)
    # The success is only refetched once its 60 s TTL ran out.
    assert after.get(122) == first.get(122) + 1, (first, after)


def test_a_refetching_slot_keeps_its_last_answer(past_ttls):
    _, _, reads = past_ttls
    # Read synchronously right after each render, while the refetch is
    # still in flight: the slot shows the last settled answer, not "".
    for r in reads:
        assert r["slots"].get("412") == "--", r
        assert r["slots"].get("122") == "62%", r
