"""
tests/snapshot_panels/test_ds_matchup_unresolved_team.py
S144-U-219: the Active Match DS matchup card and the capability-gap chip
never treat the operator's own side as the enemy.

Both rosters filtered with ``if (myTeam && pl.team === myTeam) continue;``
(web/js/panels/active_match.js _amDsSyntheticCs and the capability-gap host).
``_resolveMyTeam`` returns null when no allPlayers row carries the
activePlayer name, so that guard passed every player. On the SR ui_mock
fixture (ORDER listed first) the matchup card then took the first five rows
- the operator's own team - and, with the operator's role still BOTTOM from
liveclient.players is_active, headlined the operator's own Jinx as the lane
opponent; the capability gap was asked about all ten champions. S144-U-218
fixed the same fail-open on the THREATS strip.

Two renders of web/data/ui_mock/active_match_sr.json through a page route:
  - as authored (control): the matchup grid lists the five CHAOS champions
    and the capability-gap chip shows;
  - with an activePlayer name no roster row carries: the matchup card and the
    chip are hidden, instead of a grid of the operator's own team.
/api/ds-matchup is answered by a stand-in so nothing leaves the box. Text-
first: DOM text and the hidden flag. Synthetic names only. No pixels.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SR_FIXTURE = ROOT / "web" / "data" / "ui_mock" / "active_match_sr.json"

_ORDER = ["Jax", "LeeSin", "Syndra", "Jinx", "Thresh"]
_CHAOS = ["Teemo", "Elise", "Ekko", "Kaisa", "Blitzcrank"]


def _fixture(unmatched: bool) -> dict:
    data = json.loads(SR_FIXTURE.read_text(encoding="utf-8"))
    if unmatched:
        data["liveclient"]["activePlayer"]["summonerName"] = "NotInThisLobby#TAG"
        data["liveclient"]["activePlayer"]["riotIdGameName"] = "NotInThisLobby"
    return data


def _render(pw_browser, mock_server, unmatched: bool) -> dict:
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    body = json.dumps(_fixture(unmatched))
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route(
        "**/data/ui_mock/active_match_sr.json*",
        lambda route: route.fulfill(status=200, content_type="application/json", body=body),
    )
    page.route(
        "**/api/ds-matchup*",
        lambda route: route.fulfill(
            status=200, content_type="application/json",
            body=json.dumps({"ok": False, "error": "stand-in"}),
        ),
    )
    try:
        page.goto(mock_server.url + "/?ui_mock=1&mode=sr#active-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.querySelector('#am-sub') && "
            "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
            timeout=10_000,
        )
        # The DS cluster is painted (the sweep or relscore card has content)
        # before the matchup card and the chip are read.
        page.wait_for_function(
            "(() => { const s = document.querySelector('#csv-ds-relscore');"
            " const w = document.querySelector('#csv-sugg-ds-sweep');"
            " return (!!s && !s.hidden) || (!!w && !w.hidden); })()",
            timeout=10_000,
        )
        page.wait_for_timeout(400)
        out = page.evaluate(
            """() => {
              const m = document.querySelector('#csv-sugg-ds-matchup');
              const g = document.querySelector('#am-sugg-capability-gap');
              const cells = m ? Array.from(m.querySelectorAll('.dsm-grid-champ')) : [];
              return {
                matchupHidden: !m || m.hidden || !m.checkVisibility(),
                gridChamps: cells.map((c) => c.textContent.trim()),
                matchupText: m ? m.textContent.replace(/\\s+/g, ' ').trim().slice(0, 300) : '',
                capgapHidden: !g || g.hidden,
                capgapText: g ? g.textContent.replace(/\\s+/g, ' ').trim() : '',
                matchupBox: m ? [getComputedStyle(m).display, m.offsetHeight] : null,
                capgapBox: g ? [getComputedStyle(g).display, g.offsetHeight] : null,
                docOverflow: document.documentElement.scrollWidth
                             > document.documentElement.clientWidth,
              };
            }"""
        )
    finally:
        page.close()
        ctx.close()
    out["errors"] = errors
    return out


def test_matchup_grid_lists_the_enemy_team_when_resolved(mock_server, pw_browser):
    out = _render(pw_browser, mock_server, unmatched=False)
    assert not out["errors"], out["errors"][:3]
    assert not out["matchupHidden"], out
    assert sorted(out["gridChamps"]) == sorted(_CHAOS), out
    assert not out["capgapHidden"], out
    assert "GAP" in out["capgapText"], out
    assert out["matchupBox"][1] > 0 and out["capgapBox"][1] > 0, out
    assert not out["docOverflow"], out


def test_matchup_and_capgap_hidden_when_my_team_unresolved(mock_server, pw_browser):
    out = _render(pw_browser, mock_server, unmatched=True)
    assert not out["errors"], out["errors"][:3]
    # Before S144-U-219 the grid was the operator's own team, led by Jax and
    # headlined by the operator's own Jinx (role BOTTOM).
    for name in _ORDER:
        assert name not in out["gridChamps"], out
    assert out["matchupHidden"], out
    assert out["gridChamps"] == [], out
    assert out["capgapHidden"], out
    # A hidden card collapses: no empty box left where the card was (the
    # `[hidden]` vs `display: flex` trap, LEDGER 765).
    assert out["matchupBox"] == ["none", 0], out
    assert out["capgapBox"] == ["none", 0], out
    assert not out["docOverflow"], out
