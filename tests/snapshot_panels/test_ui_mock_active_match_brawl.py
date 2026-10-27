"""
tests/snapshot_panels/test_ui_mock_active_match_brawl.py
The out-of-game ?ui_mock=1 audit path for a brawl Active Match, and the
capability-gap chip reading the ACTIVE mode's fixture (session 144, lane
uiux, RM-969).

1. Brawl audit path. URF / ARURF / ONEFORALL / GAMEMODEX / NEXUSBLITZ route to
   MODE_BRAWL (live-reachable, CLAUDE.md Settled), but main.js _amMockUrl
   mapped sr / aram / arena / mayhem / complete / tft* only, so auditing the
   brawl Active Match needed a live brawl game.
   web/data/ui_mock/active_match_brawl.json is the SERVED shape: the
   coaches/brawl_coach.py artifact keys plus the liveclient_summary() fields
   dashboard/_state_builder.py merges into blank coach keys, with the values
   of a recorded URF match (data/rewind_history.db, queue 900) at 11:00.
   The merged game_time is load-bearing: the brawl artifact carries
   game_time_s only, and the #am-sub clock reads coach.game_time.

2. Capability-gap chip. Under ?ui_mock=1 _amFetchCapabilityGap seeded the
   chip from active_match_sr.json whatever ?mode= was, so the ARAM / Arena /
   Mayhem / complete / brawl audit pages all painted the SR fixture's
   "3 zoners" verdict, computed for a comp none of them shows. The chip now
   reads the fixture the page is rendering (amMockFixtureUrl, the one map
   main.js _amMockUrl also uses); a fixture with no capability_gap block
   leaves the chip hidden, as the live default-OFF path does.

Drive path: /?ui_mock=1&mode=<m>#active-match with an empty /api/state; the
landed render stamps "phase InProgress" into #am-sub.
"""
import json
from pathlib import Path

import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_FIXTURES = Path(__file__).resolve().parents[2] / "web" / "data" / "ui_mock"
_SR_VERDICT = json.loads(
    (_FIXTURES / "active_match_sr.json").read_text(encoding="utf-8")
)["capability_gap"]["verdict"]

# Recorded URF match, 11:00 frame: the five ORDER champions (the enemy team of
# the tracked CHAOS Smolder).
_BRAWL_ENEMIES = ["Rumble", "Vayne", "Zyra", "Veigar", "Malphite"]

# Count of fixture fetches that must have resolved before the chip is read:
# main.js _amMockLoad (1) + the capability-gap mock fetch (2).
_FIXTURE_FETCHES_JS = (
    "() => performance.getEntriesByType('resource')"
    ".filter(e => e.name.indexOf('/data/ui_mock/active_match_') >= 0).length"
)


def _open(pw_browser, mock_server, mode: str):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}#active-match",
        wait_until="domcontentloaded",
        timeout=15_000,
    )
    page.wait_for_function(
        "(document.getElementById('am-sub')?.textContent || '')"
        ".indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    return ctx, page, errors


def _chip(page) -> list:
    return page.evaluate(
        "() => { const b = document.getElementById('am-sugg-capability-gap');"
        " return [b.hidden, b.innerText]; }"
    )


def _settle_chip_fetch(page) -> None:
    page.wait_for_function(f"({_FIXTURE_FETCHES_JS})() >= 2", timeout=10_000)
    # The fetch resolving and its .json() / callback are separate ticks.
    page.wait_for_timeout(400)


def test_brawl_ui_mock_renders_the_served_brawl_state(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, "brawl")
    try:
        assert page.evaluate("document.body.dataset.uiMock") == "1"
        assert page.locator("#view-active-match").is_visible()
        # The clock is the merged liveclient game_time, never a dash.
        assert page.evaluate(
            "document.getElementById('am-sub').textContent"
        ) == "BRAWL - Smolder - 11:00 - phase InProgress"
        call = page.evaluate(
            "document.getElementById('am-call-body').innerText"
        )
        assert "RIGHT NOW" in call and "Malphite is 10/1/1" in call
        assert "GROUP MID WITH ZILEAN AND POKE" in call
        assert "Their mid tier-1 is low" in call
        champs = page.evaluate(
            "() => Array.from(document.querySelectorAll("
            "'#view-active-match .dsm-grid-champ')).map(e => e.textContent)"
        )
        assert champs == _BRAWL_ENEMIES, champs
        assert page.evaluate(
            "document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth"
        ), "horizontal overflow in the brawl mock"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [brawl]: {errors[:3]}"


def test_capgap_chip_paints_the_sr_fixture_verdict_on_sr(mock_server, pw_browser):
    """Positive control: the SR fixture carries a capability_gap block, so the
    chip shows it (and the hidden assertions below are not vacuous)."""
    ctx, page, errors = _open(pw_browser, mock_server, "sr")
    try:
        page.wait_for_function(
            "!document.getElementById('am-sugg-capability-gap').hidden",
            timeout=10_000,
        )
        hidden, text = _chip(page)
        assert hidden is False
        assert _SR_VERDICT in text
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [sr]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["aram", "arena", "mayhem", "complete", "brawl"])
def test_capgap_chip_never_borrows_the_sr_fixture(mode, mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        _settle_chip_fetch(page)
        hidden, text = _chip(page)
        assert _SR_VERDICT not in text, (
            f"{mode} audit page paints the SR fixture's capability gap"
        )
        assert hidden is True, f"{mode}: chip shown with no fixture gap: {text!r}"
        urls = page.evaluate(
            "() => performance.getEntriesByType('resource').map(e => e.name)"
            ".filter(n => n.indexOf('/data/ui_mock/active_match_') >= 0)"
        )
        assert not any(u.endswith("/active_match_sr.json") for u in urls), urls
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"
