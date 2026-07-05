"""
tests/snapshot_panels/test_home_snapshot_card.py
Home player-snapshot adapter (spec 7.1) - Task 6 (2026-07-04).

Wires the Home view to renderPlayerSnapshot (Task 5, web/js/panels/
player_snapshot.js) via GET /api/player-snapshot?mode=<tab>&hours=24
(Task 4, dashboard/routes_player_snapshot.py). main.js's _homeFetchAndRender
(the SAME handler test_home_mode_tabs.py drives - it refetches
/api/home/summary on every _homeApplyModeTab tab change) now also fetches
the snapshot model and merges header.rank_tier/rank_lp from the home-summary
payload's `rank` dict ({ranked, tier, division, lp, win_rate_pct, display} -
core/lcu_ranked shape; NO rank_tier/rank_lp/level/name keys exist on it
literally, so the merge maps rank.display -> header.rank_tier and rank.lp ->
header.rank_lp). name/level are not available anywhere in the frontend
payload (grepped: no summonerName/summonerLevel field reaches main.js), so
they stay null - the card's own "-" no-reflow sentinel covers that, per
feedback_no_reflow_on_data_absence.

Spec 7.1 absorb: the card now carries rank + KDA + momentum, so the
standalone #home-hero-rank-tier (+ #home-hero-rank box), the KDA hero chip,
and #home-hero-headline are hidden (visual-only per
feedback_field_remove_visual_only - the JS setters keep running so no wiring
is ripped out). #home-hero-rank-wl (W/L pips) and the CS hero chip stay
visible, per spec 7.1's REFACTOR (not absorb) ruling.

Uses the same mock-server + Playwright harness as test_home_mode_tabs.py.
Under ?ui_mock=1, /api/home/summary short-circuits to the static fixture
(conftest's do_GET has no special case for it - the fetch hits the real
static file at /data/ui_mock/home.json); /api/player-snapshot is a real
fetch through the mock server's catch-all (do_GET returns {} for any
unmatched /api/* path), so page.route stubs are required to get a
deterministic model.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURE = ROOT / "web" / "data" / "ui_mock" / "home.json"

_TABS_READY = (
    "document.getElementById('home-overlay') && "
    "!!document.getElementById('home-overlay').dataset.modeTab"
)

_SNAPSHOT_MODEL = {
    "header": {"name": None, "rank_tier": None, "rank_lp": None, "level": None,
               "streak": {"kind": "win", "n": 2}, "champion_id": 222,
               "result": None},
    "dial": {"value": 71, "band": "good", "label": "SR last 24h"},
    "minis": [
        {"key": "kda", "value": "3.40", "provenance": "source_truth"},
        {"key": "winrate", "value": "60%", "provenance": "source_truth"},
        {"key": "kp", "value": "55%", "provenance": "inferred"},
    ],
    "bars": [
        {"key": "income", "label": "INCOME", "score": 62,
         "provenance": "source_truth"},
        {"key": "combat", "label": "COMBAT", "score": 71,
         "provenance": "source_truth"},
        {"key": "objectives", "label": "OBJECTIVES", "score": 48,
         "provenance": "source_truth"},
        {"key": "vision", "label": "VISION", "score": 55,
         "provenance": "source_truth"},
    ],
    "tags": [
        {"label": "Aggressive", "tone": "strong"},
        {"label": "Consistent", "tone": "neutral"},
        {"label": "Weak Farm", "tone": "weak"},
    ],
    "profile_ref": {"mode": "sr", "window": "24h", "match_id": None},
    "confidence": "high", "sample_n": 12, "empty": False,
}

_RANK_PAYLOAD = {
    "ranked": True, "tier": "GOLD", "division": "II", "lp": 47,
    "wins": 30, "losses": 20, "win_rate_pct": 60, "display": "Gold II",
}


def _open_home(pw_browser, mock_server, snapshot_calls=None, w=1920, h=1080,
                start_tab="SR"):
    """Mirrors test_home_mode_tabs.py's _open_home, plus route stubs for
    /api/player-snapshot (model fixed per this test) and /api/home/summary
    (rank payload merged in so the header-merge path is exercised).

    start_tab defaults to SR (not the fresh-browser ALL default): per spec
    7.1 decision #1 the snapshot card intentionally stays hidden on the ALL
    tab (no single mode to request), so any test that wants to see the
    mounted card must first land on/click a real mode tab - pass
    start_tab=None to keep the ALL default when a test wants that exact
    hidden-on-ALL behavior."""
    from tests.snapshot_panels.conftest import _WS_STUB

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["rank"] = _RANK_PAYLOAD
    body = json.dumps(fixture)

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))

    def _fulfill_home(r):
        r.fulfill(status=200, content_type="application/json", body=body)
    page.route("**/data/ui_mock/home.json", _fulfill_home)
    page.route("**/api/home/summary*", _fulfill_home)

    def _fulfill_snapshot(r):
        if snapshot_calls is not None:
            snapshot_calls.append(r.request.url)
        r.fulfill(status=200, content_type="application/json",
                   body=json.dumps(_SNAPSHOT_MODEL))
    page.route("**/api/player-snapshot*", _fulfill_snapshot)

    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(_TABS_READY, timeout=10_000)
    if start_tab:
        page.locator(f'.home-mode-tab[data-hmode="{start_tab}"]').click()
        page.wait_for_function(
            "document.getElementById('home-overlay').dataset.modeTab "
            f"=== '{start_tab}'",
            timeout=5_000,
        )
    return ctx, page, errors


def test_snapshot_card_present_in_home_mount(mock_server, pw_browser):
    """The card mounts into #home-snapshot-card and renders the model's
    dial band/value once a real mode tab (SR) is active - proves
    _renderHomeSnapshot fires from the same _homeFetchAndRender().then that
    test_home_mode_tabs.py drives (spec 7.1 decision #1: the card stays
    hidden on the ALL tab by design - see
    test_snapshot_card_hidden_on_all_tab below)."""
    calls: list[str] = []
    ctx, page, errors = _open_home(pw_browser, mock_server, calls)
    try:
        # renderPlayerSnapshot stamps data-testid on the mount element
        # itself (#home-snapshot-card IS the card, no wrapper child).
        page.wait_for_selector(
            '#home-snapshot-card[data-testid="player-snapshot"]',
            timeout=10_000,
        )
        card = page.locator(
            '#home-snapshot-card[data-testid="player-snapshot"]'
        )
        assert card.count() == 1, "player-snapshot card did not mount in Home"
        dial = card.locator(".ps-dial")
        assert dial.get_attribute("data-band") == "good", (
            "dial band does not match the stubbed model"
        )
        value = card.locator(".ps-dial-value").text_content().strip()
        assert value == "71", f"dial value {value!r} != stubbed 71"
        assert calls, "no /api/player-snapshot request observed"
        assert "mode=sr" in calls[0], (
            f"initial fetch missing mode=sr: {calls[0]!r}"
        )
        assert "hours=24" in calls[0], (
            f"initial fetch missing hours=24: {calls[0]!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [snapshot card present]: {errors[:3]}"


def test_snapshot_card_refetches_on_mode_tab_switch(mock_server, pw_browser):
    """Switching the mode tab (the same _homeApplyModeTab handler
    test_home_mode_tabs.py drives) refetches /api/player-snapshot with the
    new tab's lowercased mode, and the card re-renders (still the stubbed
    model, since the stub is mode-agnostic here; the URL is the proof)."""
    calls: list[str] = []
    ctx, page, errors = _open_home(pw_browser, mock_server, calls)
    try:
        page.wait_for_selector(
            '#home-snapshot-card[data-testid="player-snapshot"]',
            timeout=10_000,
        )
        calls.clear()
        page.locator('.home-mode-tab[data-hmode="ARAM"]').click()
        page.wait_for_function(
            "document.getElementById('home-overlay').dataset.modeTab "
            "=== 'ARAM'",
            timeout=5_000,
        )
        # calls is a plain python list mutated by the route handler closure
        # (not page-side), so poll it directly rather than page.evaluate.
        for _ in range(20):
            if calls:
                break
            page.wait_for_timeout(50)
        assert calls, "no /api/player-snapshot refetch on ARAM tab switch"
        assert "mode=aram" in calls[-1], (
            f"ARAM tab refetch missing mode=aram: {calls[-1]!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [snapshot refetch on tab switch]: {errors[:3]}"


def test_absorbed_rank_tier_hidden_no_duplicate(mock_server, pw_browser):
    """Spec 7.1 absorb: the standalone #home-hero-rank-tier (+ its
    containing #home-hero-rank box) is hidden once the card carries rank -
    no duplicate rank identity on the page. The KDA hero chip and the
    momentum headline are hidden too (absorbed into the card); the W/L pip
    strip (#home-hero-rank-wl) and the CS hero chip stay visible (spec 7.1
    REFACTOR, not absorb)."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        page.wait_for_selector(
            '#home-snapshot-card[data-testid="player-snapshot"]',
            timeout=10_000,
        )
        rank_box = page.locator("#home-hero-rank")
        assert not rank_box.is_visible(), (
            "absorbed #home-hero-rank still visible (duplicate rank)"
        )
        kda_chip = page.locator('.home-hero-chip[data-metric="kda"]')
        assert not kda_chip.is_visible(), (
            "absorbed KDA hero chip still visible"
        )
        headline = page.locator("#home-hero-headline")
        assert not headline.is_visible(), (
            "absorbed momentum headline still visible"
        )
        # Kept (not absorbed): W/L pips + CS chip.
        wl = page.locator("#home-hero-rank-wl")
        assert wl.is_visible(), "#home-hero-rank-wl (kept per spec) hidden"
        cs_chip = page.locator('.home-hero-chip[data-metric="cs_per_min"]')
        assert cs_chip.is_visible(), (
            "CS hero chip (kept per spec) hidden"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [absorbed rank hidden]: {errors[:3]}"


def test_snapshot_card_hidden_on_all_tab(mock_server, pw_browser):
    """Spec 7.1 decision #1: the ALL tab has no single mode to request, so
    the mount stays hidden - a fresh browser context (no persisted tab
    choice) lands on ALL by default (_homeModeTabLoad) and must never fire
    /api/player-snapshot or show the card until a real mode tab is picked."""
    calls: list[str] = []
    ctx, page, errors = _open_home(
        pw_browser, mock_server, calls, start_tab=None
    )
    try:
        mode = page.evaluate(
            "document.getElementById('home-overlay').dataset.modeTab"
        )
        assert mode == "ALL", f"fresh context did not default to ALL: {mode!r}"
        page.wait_for_timeout(300)
        mount = page.locator("#home-snapshot-card")
        assert not mount.is_visible(), "card visible on the ALL tab"
        assert not calls, (
            f"/api/player-snapshot fetched on ALL tab: {calls!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [card hidden on ALL]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
