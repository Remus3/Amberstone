"""
tests/snapshot_panels/test_team_context_rate_limited.py
A Riot API rate limit must render as a rate limit, not as missing data.

Before the fix the fan-out could not tell a 429 from "no rank", so a
throttled player painted exactly like an empty skeleton: a dashed "-" rank
chip and a status of "partial". The backend now marks such an entry
`riot_status: "rate_limited"` (dashboard/routes_team_context.py) and the
panel must say so in friendly words - never the raw HTTP status.

RED before the fix: the old renderer ignored riot_status, so the rank chip
read "-" and the status read "partial".
"""
import json

_QUEUE_ID = 450


def _entry(name, team_id, rank="", riot_status=""):
    return {
        "puuid": "puuid-" + name.lower(),
        "summoner_name": name,
        "team_id": team_id,
        "locked_champion": "Ahri",
        "rank": rank,
        "mastery_on_locked": 0,
        "w_l_streak_7": [0, 0],
        "mains": [],
        "win_rate_recent": 0.0,
        "riot_status": riot_status,
    }


def _fixture(partial):
    return {
        "mode_key": "client",
        "coach": {
            "team_context": {
                "allies": [
                    _entry("Throttled", 100, riot_status="rate_limited"),
                    _entry("Fine", 100, rank="GOLD II 40 LP"),
                ],
                "enemies": [_entry("Plain", 200)],
                "refreshed_at": "2026-09-20T12:00:00+00:00",
                "partial": partial,
                "queue_id": _QUEUE_ID,
            },
        },
        "liveclient": None,
        "lcu": {"phase": "ChampSelect", "queue_id": _QUEUE_ID},
    }


def _open(mock_server, pw_browser, partial):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = json.loads(json.dumps(_fixture(partial)))
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/", wait_until="domcontentloaded", timeout=15_000
    )
    page.wait_for_function(
        "document.querySelectorAll('#tc-allies .tc-slot').length === 5",
        timeout=10_000,
    )
    return ctx, page, errors


def _rank_texts(page, host):
    return page.eval_on_selector_all(
        f"#{host} .tc-slot-rank", "els => els.map(e => e.textContent)"
    )


def test_rate_limited_entry_reads_rate_limited_not_dash(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, partial=True)
    try:
        ranks = _rank_texts(page, "tc-allies")
        assert ranks[0] == "rate limited", ranks
        assert ranks[1] == "GOLD II 40 LP", ranks
        # A plain not-yet-populated entry keeps the skeleton dash.
        assert _rank_texts(page, "tc-enemies")[0] == "-"
        rl_cls = page.eval_on_selector(
            "#tc-allies .tc-slot-rank", "el => el.className")
        assert "tc-slot-rl" in rl_cls and "skel" not in rl_cls

        status = page.eval_on_selector("#tc-status", "el => el.textContent")
        assert status.startswith("Riot API rate limited - retrying"), status
        # Never the raw status code.
        panel = page.eval_on_selector(
            "#cs-team-context-block", "el => el.textContent")
        assert "429" not in panel
        assert not errors, f"page errors: {errors}"
    finally:
        ctx.close()


def test_rate_limited_after_fanout_done_says_unavailable(mock_server, pw_browser):
    ctx, page, errors = _open(mock_server, pw_browser, partial=False)
    try:
        status = page.eval_on_selector("#tc-status", "el => el.textContent")
        assert status.startswith(
            "Riot API rate limited - some data unavailable"), status
        assert "retrying" not in status
        assert not errors, f"page errors: {errors}"
    finally:
        ctx.close()
