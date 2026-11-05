"""
tests/snapshot_panels/test_champ_select_adaptation_fetch_s144q43.py
RM-1211 - a champ-select pick no longer aborts handleLcuEnvelope.

The defect, measured at local main fc123ec87: handleChampSelect
(web/js/panels/champ_select.js) called fetchAdaptation, which is
module-local to web/js/main.js. Once a champion was picked and the
champion-name index had loaded, that bare call threw a ReferenceError. The
LCU poller wraps handleLcuEnvelope in a silent try/catch, so nothing reached
the console as a page error; the throw simply skipped every line after it:
the pre-game /api/adaptation fetch never happened, and handleLcuEnvelope's
own follow-ups (auto-accept sync, Home phase chip, view re-derive, lobby
refresh, champ-select view render) never ran for any envelope of a pick.

This drives the REAL poll path in headless Chromium (no ui_mock): /api/state
is routed to an LCU envelope, first with no pick, then with a pick. Two
witnesses, both red on the base:

1. /api/adaptation is requested with the picked champion, the SR ranked mode
   and the resolved enemy - the call the champ-select code exists to make.
2. _syncAutoAcceptFromConfig, the line right AFTER handleChampSelect in
   handleLcuEnvelope, reflects the envelope's config.auto_accept flip into
   the rc-lobby-auto-accept mirror - proof the function ran to its end.

3. NO /api/champ-select-coach POST. The same throw had also kept the live
   Haiku pick-advisor POST further down handleChampSelect from ever firing.
   Removing the throw must not switch that paid call back on as a side
   effect: it stays OFF behind champ_select.js _CS_LIVE_COACH_ENABLED until
   RM-1212 decides it (adjudicated in s144 queue cycle 68).

A page-error assertion alone would be vacuous here, because the poller's
catch swallows the ReferenceError; that is why the witnesses are behavioural.
Champion ids are DDragon static champion keys from web/data/champions_index
.json, not player data.
"""
import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from tests.snapshot_panels._route_match import on_path

ROOT = Path(__file__).resolve().parent.parent.parent
_INDEX = json.loads(
    (ROOT / "web" / "data" / "champions_index.json").read_text(encoding="utf-8"))
_ME_ID, _FOE_ID = 103, 266          # DDragon keys, resolved below


def _name(cid):
    return _INDEX["byId"][str(cid)]


def _envelope(pick: bool) -> dict:
    return {
        "phase": "ChampSelect",
        "config": {"auto_accept": pick},
        "champ_select": {
            "queue_id": 420,
            "is_aram": False,
            "my_champion": _ME_ID if pick else 0,
            "my_team": [{"championId": _ME_ID if pick else 0}],
            "their_team": [{"championId": _FOE_ID}],
            "bench": [],
        },
    }


def test_a_pick_fetches_adaptation_and_finishes_the_envelope(
        mock_server, pw_browser):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080})
    live = {"lcu": _envelope(pick=False)}
    adapt_urls: list = []
    coach_posts: list = []

    def _state(route, request):
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps(live))

    def _adaptation(route, request):
        adapt_urls.append(request.url)
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"present": False}))

    ctx.route(on_path("/api/state"), _state)
    def _coach(route, request):
        coach_posts.append(request.post_data or "")
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"ok": False}))

    ctx.route(on_path("/api/adaptation"), _adaptation)
    ctx.route(on_path("/api/champ-select-coach"), _coach)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        with page.expect_response(
                lambda r: "/data/champions_index.json" in r.url,
                timeout=15_000):
            page.goto(mock_server.url + "/#home",
                      wait_until="domcontentloaded", timeout=15_000)
        # No pick yet: the poller runs handleLcuEnvelope to its end and the
        # auto-accept mirror reads "0". This also proves the poll is live.
        page.wait_for_function(
            "localStorage.getItem('rc-lobby-auto-accept') === '0'",
            timeout=20_000)
        assert adapt_urls == [], "no pick yet, no adaptation request"

        live["lcu"] = _envelope(pick=True)
        page.wait_for_function(
            "localStorage.getItem('rc-lobby-auto-accept') === '1'",
            timeout=20_000)
        page.wait_for_timeout(500)
        assert adapt_urls, "a pick in champ select must request /api/adaptation"
        q = parse_qs(urlsplit(adapt_urls[0]).query)
        assert q.get("champion") == [_name(_ME_ID)], q
        assert q.get("mode") == ["sr_ranked"], q
        assert q.get("enemies") == [_name(_FOE_ID)], q
        assert not [e for e in errors if "fetchAdaptation" in e], errors
        # The live Haiku POST is debounced 6 s from its first eligible pick,
        # so the first pick envelope would already have fired it.
        assert coach_posts == [], (
            "a pick must not fire the paid /api/champ-select-coach POST "
            f"(RM-1212 owns that decision): {coach_posts}")
    finally:
        ctx.close()
