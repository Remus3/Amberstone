"""
tests/snapshot_panels/test_last_match_map_objectives.py
The Post Game Review team chart picks its objective rows by MAP, not by a
not-ARAM-not-Arena default (session 144, lane uiux, RM-976).

web/js/panels/last_match.js _setChart drew Dragons / Barons / Heralds for
every 5v5 game that was neither ARAM nor Arena (isSr = !isAram && !isArena).
A Nexus Blitz game (mapId 21, queue 1300, recorded by performance_tracker as
mode "BRAWL") has no dragon or baron pit, so the chart showed "Dragons 0 vs
0" and "Barons 0 vs 0" as if the teams had tied on them. Measured over the
real match store (data/rewind_history.db, read-only): the 4 NEXUSBLITZ games
carry 0 dragonKills and 0 baronKills on all 8 team rows, but 5
riftHeraldKills, so Riot does record a herald there.

Rule pinned here:
- mapId 11 (Summoner's Rift) keeps Dragons, Barons and Heralds;
- mapId 21 (Nexus Blitz) keeps Heralds only;
- any other known map draws no pit-objective row;
- a payload with no map_id keeps the old 5v5 default, so a pre-map row
  renders as before.

Drive path: the Brawl ui_mock (web/data/ui_mock/last_match_brawl.json, a URF
game on mapId 11) is rewritten in flight by page.route. The Nexus Blitz
variant takes its game fields and BOTH team rows from one real NEXUSBLITZ
game in rewind_history (team 100 lost: 1 tower; team 200 won: 2 towers, 2
heralds, 1 inhibitor, 0 dragons, 0 barons). No id is copied (RM-906): the
fixture's synthetic ids stay.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
BRAWL = ROOT / "web" / "data" / "ui_mock" / "last_match_brawl.json"
SR = ROOT / "web" / "data" / "ui_mock" / "last_match_sr.json"

_CHART = """() => Array.from(
  document.querySelectorAll("#lm-chart-list > .lm-chart-row")
).map((r) => [
  r.querySelector(".lm-chart-label").textContent.trim(),
  r.querySelector(".lm-chart-bar-ally .lm-chart-bar-value").textContent.trim(),
  r.querySelector(".lm-chart-bar-enemy .lm-chart-bar-value").textContent.trim(),
])"""

_PIT_ROWS = ("Dragons", "Barons", "Heralds")


def _team(src, **over):
    t = dict(src)
    t.update(over)
    return t


def _nexus_blitz(payload):
    e = payload["match"]["enriched"]
    e["map_id"] = 21
    e["queue_id"] = 1300
    e["game_mode"] = "NEXUSBLITZ"
    ally, enemy = e["teams"]
    # One real NEXUSBLITZ game's team rows (rewind_history, map 21).
    e["teams"] = [
        _team(ally, win=False, tower_kills=1, dragon_kills=0, baron_kills=0,
              rift_herald_kills=0, inhibitor_kills=0, horde_kills=0,
              first_dragon=False, first_baron=False),
        _team(enemy, win=True, tower_kills=2, dragon_kills=0, baron_kills=0,
              rift_herald_kills=2, inhibitor_kills=1, horde_kills=0,
              first_dragon=False, first_baron=False),
    ]
    return payload


def _map(map_id):
    def edit(payload):
        payload["match"]["enriched"]["map_id"] = map_id
        return payload
    return edit


def _drop_map_id(payload):
    payload["match"]["enriched"].pop("map_id", None)
    return payload


def _chart(mock_server, pw_browser, mode, fixture, edit):
    body = json.dumps(edit(json.loads(fixture.read_text(encoding="utf-8"))))
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.route(
        "**/data/ui_mock/" + fixture.name + "*",
        lambda route: route.fulfill(
            status=200, content_type="application/json", body=body),
    )
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#last-match",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "(() => document.querySelectorAll("
            "'#lm-chart-list > .lm-chart-row').length > 0)()",
            timeout=10_000,
        )
        rows = page.evaluate(_CHART)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return {label: (a, b) for label, a, b in rows}, [r[0] for r in rows]


def test_nexus_blitz_chart_drops_the_dragon_and_baron_rows(
        mock_server, pw_browser):
    chart, labels = _chart(mock_server, pw_browser, "brawl", BRAWL,
                           _nexus_blitz)
    assert "Dragons" not in chart, labels
    assert "Barons" not in chart, labels
    # The herald is real on Nexus Blitz and the towers row is mode-agnostic.
    assert chart["Heralds"] == ("0", "2")
    assert chart["Towers"] == ("1", "2")
    assert labels[-2:] == ["Towers", "Heralds"]


@pytest.mark.parametrize("map_id", [12, 30, 35])
def test_another_known_map_draws_no_pit_objective_row(
        mock_server, pw_browser, map_id):
    # The brawl fixture's teams carry real Rift counts (dragons 2 vs 2,
    # barons 0 vs 1): the gate, not empty data, must drop them.
    chart, labels = _chart(mock_server, pw_browser, "brawl", BRAWL,
                           _map(map_id))
    assert not [r for r in _PIT_ROWS if r in chart], labels
    assert chart["Towers"] == ("3", "11")


def test_rift_brawl_keeps_all_three_pit_rows(mock_server, pw_browser):
    # Positive control for the gate: the unedited URF game on mapId 11.
    chart, labels = _chart(mock_server, pw_browser, "brawl", BRAWL,
                           lambda p: p)
    assert chart["Dragons"] == ("2", "2")
    assert chart["Barons"] == ("0", "1")
    assert chart["Heralds"] == ("0", "0")
    assert labels[-4:] == ["Towers", "Dragons", "Barons", "Heralds"]


def test_payload_without_map_id_keeps_the_rift_default(
        mock_server, pw_browser):
    # A row ingested without mapId must render exactly as before the gate.
    chart, labels = _chart(mock_server, pw_browser, "sr", SR, _drop_map_id)
    for row in _PIT_ROWS:
        assert row in chart, labels
