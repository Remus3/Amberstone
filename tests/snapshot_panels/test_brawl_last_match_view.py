"""
tests/snapshot_panels/test_brawl_last_match_view.py
The Brawl (URF) Post Game Review rendered from a fixture (session 144, lane
uiux, RM-974).

web/js/panels/last_match.js _lmMockUrl mapped sr / aram / arena / tft only,
so a Brawl last match (URF / ARURF / ONEFORALL / NEXUSBLITZ / ULTBOOK /
GAMEMODEX, recorded by performance_tracker as mode "BRAWL") could be audited
only right after a real Brawl game. ?ui_mock=1&mode=brawl now loads
web/data/ui_mock/last_match_brawl.json, a payload assembled by RC's own
builders over one real URF game's stat line (queue 900, mapId 11; synthetic
names and ids), and this file pins what the League PGR body renders from it
in real headless Chromium.

What the render must show for a Brawl game:
- the hero reads the BRAWL mode tag, the D grade the brawl rubric gives a
  3/13/9 line, and a DEFEAT pill (a 5v5 loss, not Arena's neutral pill);
- URF runs on Summoner's Rift, so the team comparison carries the tower,
  dragon, baron and herald rows with the real objective counts;
- the WPA phase strip and win-prob graph stay hidden (the model is trained
  on SR timelines; mode "BRAWL" is not an SR mode string);
- the quick review columns carry the builder's own text, and nothing
  overflows the 1920 baseline.

Drive path mirrors test_last_match_view.py: /?ui_mock=1&mode=brawl#last-match
with an empty /api/state; #lm-mode-tag leaving "-" is the landing signal.
"""
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "web" / "data" / "ui_mock" / "last_match_brawl.json"

_READ = """() => {
  const txt = (id) => {
    const el = document.getElementById(id);
    return el ? el.textContent.trim() : null;
  };
  const rows = Array.from(document.querySelectorAll("#lm-chart-list > .lm-chart-row"));
  const qr = (id) => Array.from(document.querySelectorAll("#" + id + " > li"))
    .map((li) => li.textContent.trim());
  const wpa = document.getElementById("lm-wpa-wrap");
  return {
    tag: txt("lm-mode-tag"),
    champ: txt("lm-champion-name"),
    grade: txt("lm-grade-badge"),
    result: txt("lm-result-badge"),
    kda: txt("lm-kda-text"),
    tftHidden: document.getElementById("lm-tft").hidden,
    bodyDisplay: getComputedStyle(document.getElementById("lm-body")).display,
    chart: rows.map((r) => [
      r.querySelector(".lm-chart-label").textContent.trim(),
      r.querySelector(".lm-chart-bar-ally .lm-chart-bar-value").textContent.trim(),
      r.querySelector(".lm-chart-bar-enemy .lm-chart-bar-value").textContent.trim(),
    ]),
    ally: document.querySelectorAll("#lm-tc-ally-list > li").length,
    enemy: document.querySelectorAll("#lm-tc-enemy-list > li").length,
    wpaHidden: wpa ? wpa.hidden : null,
    qrRight: qr("lm-qr-right"),
    qrWrong: qr("lm-qr-wrong"),
    qrChronic: qr("lm-qr-chronic"),
    pageOverflow: document.documentElement.scrollWidth - window.innerWidth,
  };
}"""


# The WPA phase strip (post_game_phases.js) and win-prob graph
# (pgr_winprob.js) fetch these; under ?ui_mock=1 the graph reads the local
# pgr_winprob.json fixture instead of the route.
_WPA_URLS = ("/api/post-game-wpa", "/data/ui_mock/pgr_winprob.json")


def _open_pgr(mock_server, pw_browser, mode):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    requests: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.on("request", lambda req: requests.append(req.url))
    page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}#last-match",
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "(() => { const t = document.getElementById('lm-mode-tag');"
        " const v = t ? t.textContent.trim() : '';"
        " return v !== '' && v !== '-'; })()",
        timeout=10_000,
    )
    return ctx, page, errors, requests


def _wpa_requests(requests):
    return [u for u in requests if any(w in u for w in _WPA_URLS)]


@pytest.fixture
def brawl_pgr(mock_server, pw_browser):
    ctx, page, errors, requests = _open_pgr(mock_server, pw_browser, "brawl")
    try:
        r = page.evaluate(_READ)
        # _setPhases runs inside the same render as the mode tag; give any
        # WPA fetch it would have issued time to reach the request log.
        page.wait_for_timeout(500)
        r["wpaRequests"] = _wpa_requests(requests)
        yield r, errors
    finally:
        page.close()
        ctx.close()


def test_brawl_mock_renders_the_league_body_not_the_tft_card(brawl_pgr):
    r, errors = brawl_pgr
    assert r["tftHidden"] is True
    assert r["bodyDisplay"] != "none"
    assert r["pageOverflow"] <= 0, r["pageOverflow"]
    assert not errors, errors[:3]


def test_brawl_hero_reads_mode_grade_and_a_defeat_pill(brawl_pgr):
    r, _ = brawl_pgr
    assert r["tag"] == "BRAWL"
    assert r["champ"] == "Quinn"
    assert r["kda"] == "3/13/9"
    # performance_tracker.calculate_brawl_rating on 3/13/9 scores 23.5 -> D.
    assert r["grade"] == "D"
    assert r["result"].startswith("DEFEAT"), r["result"]


def test_brawl_team_compare_keeps_the_rift_objective_rows(brawl_pgr):
    r, _ = brawl_pgr
    assert r["ally"] == 5 and r["enemy"] == 5
    chart = {label: (ally, enemy) for label, ally, enemy in r["chart"]}
    assert chart["Kills"] == ("20", "53")
    assert chart["Gold"] == ("58.4k", "73.1k")
    # URF is played on Summoner's Rift: the objective rows are real here.
    assert chart["Towers"] == ("3", "11")
    assert chart["Dragons"] == ("2", "2")
    assert chart["Barons"] == ("0", "1")
    assert chart["Heralds"] == ("0", "0")
    # RM-977: the URF game's real grub count reaches the chart.
    assert chart["Void Grubs"] == ("0", "3")


def test_brawl_hides_the_sr_trained_wpa_strip(brawl_pgr):
    # lm-wpa-wrap starts hidden and an empty WPA payload also hides it, so
    # the discriminating check is that no WPA source is ever fetched: the
    # last_match.js _setPhases "Skip non-SR modes" gate returns first.
    r, _ = brawl_pgr
    assert r["wpaHidden"] is True
    assert r["wpaRequests"] == [], r["wpaRequests"]


def test_sr_positive_control_does_fetch_the_wpa_source(mock_server, pw_browser):
    # Positive control for the check above: the SR fixture passes the same
    # gate, so its render must reach a WPA source - proving the request log
    # would see one.
    ctx, page, errors, requests = _open_pgr(mock_server, pw_browser, "sr")
    try:
        page.wait_for_timeout(500)
        assert _wpa_requests(requests), "SR render fetched no WPA source"
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]


def test_brawl_quick_review_carries_the_builder_text(brawl_pgr):
    r, _ = brawl_pgr
    assert r["qrRight"] == ["No standout positives this match"]
    assert r["qrWrong"][:3] == [
        "Lost first blood", "Lost first tower", "Team kill deficit (20-53)",
    ]
    assert len(r["qrWrong"]) == 5
    assert r["qrChronic"] == ["Recent grade slump (15/20 at D/F)"]


def test_brawl_fixture_is_ascii_and_carries_no_real_riot_ids():
    raw = FIXTURE.read_bytes()
    assert all(b < 0x80 for b in raw)
    assert b"\r" not in raw
    text = raw.decode("ascii")
    # RM-906: synthetic ids only - no platform-prefixed match id, no puuid.
    for token in ("NA1_", "EUW1_", "KR_", "puuid"):
        assert token not in text, token
