"""Rendered-Chromium proof of the NEXT BUY overlay widget (w-nextbuy).

BACKLOG "Overlay HUD micro-lifts" slices (b) + (c): gold remaining to the next
Daemon-Slayer-recommended item, and the free yellow-trinket upgrade nudge as a
precomputed rule line. Both are pure arithmetic over /api/state fields
(web/js/lib/next_buy_model.js); this file proves they actually PAINT on the
overlay route.

Drive path mirrors test_objective_gauges_view.py: a LIVE (non-ui_mock) SSE
envelope with mode_key=sr + a liveclient block carrying the exact producers -
gold (dashboard/_liveclient.py:148), sr_items (:389-396), owned_items (:256),
game_time_s (:144).

Item cost resolution is real here: the harness serves web/data/items_index.json
+ web/data/items_costs.json as static files, so ITEM_COSTS/_resolveItemId
populate exactly as they do live. The recipe graph (/api/dictionary/items)
returns {} under the mock, so NO component credit is applied - the widget
correctly charges the full remaining cost, which is the honest under-credit the
model documents.

Covered:
  1. in-game SR: all three rows paint with the computed gold + trinket nudge,
     at the movable ovx-widget field registration.
  2. no-reflow: the row count + geometry are identical with and without a
     firing trinket rule.
  3. idle (empty envelope): the widget hides entirely - no placeholder.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRATCH = ROOT / "_scratch"

# Kraken Slayer id 6672 costs 3000g in web/data/items_costs.json.
_KRAKEN_COST = 3000
_GOLD = 500

# A live SR envelope at 15:00 (900s) - stage "mid" by the clock, so the free
# trinket upgrade rule fires (core/build_planner/replan.py:684-689).
_SR_STATE = {
    "mode_key": "sr",
    "coach": {"action": "Push mid", "immediate": "Group up", "kda": "1/0/0"},
    "liveclient": {
        "level": 11,
        "game_time_s": 900,
        "gold": _GOLD,
        "owned_items": ["Berserker's Greaves", "Stealth Ward"],
        "sr_items": [
            {"name": "Berserker's Greaves", "owned": True, "next": False},
            {"name": "Kraken Slayer", "owned": False, "next": True},
        ],
        "objective_events": [],
    },
}

# Same game, but the yellow trinket has already been upgraded - the rule line
# falls to the "-" sentinel WITHOUT the widget changing shape.
_SR_STATE_NO_TRINKET = {
    "mode_key": "sr",
    "coach": {"action": "Push mid", "immediate": "Group up", "kda": "1/0/0"},
    "liveclient": {
        "level": 11,
        "game_time_s": 900,
        "gold": _GOLD,
        "owned_items": ["Berserker's Greaves", "Farsight Alteration"],
        "sr_items": [
            {"name": "Berserker's Greaves", "owned": True, "next": False},
            {"name": "Kraken Slayer", "owned": False, "next": True},
        ],
        "objective_events": [],
    },
}


def _open_live(pw_browser, mock_server, data, query="?overlay=1&mode=sr"):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = data
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/" + query,
              wait_until="domcontentloaded", timeout=15_000)
    return ctx, page, errors


def _css(page, selector, prop):
    return page.eval_on_selector(
        selector, "(el, p) => getComputedStyle(el).getPropertyValue(p)", prop
    )


def _row_text(page, key):
    return page.eval_on_selector(
        f'#am-next-buy .nb-row[data-nb-row="{key}"] .nb-v',
        "el => el.textContent")


def _wait_rows(page):
    page.wait_for_function(
        "() => { const m = document.getElementById('am-next-buy');"
        " return m && !m.hidden && m.querySelectorAll('.nb-row').length === 3; }",
        timeout=10_000,
    )


def test_next_buy_renders_live_sr_state(mock_server, pw_browser):
    """A live SR envelope paints NEXT / GOLD / TRINKET with the computed
    figures, at the movable ovx-widget field registration."""
    ctx, page, errors = _open_live(pw_browser, mock_server, dict(_SR_STATE))
    try:
        _wait_rows(page)
        assert _row_text(page, "item") == "Kraken Slayer"
        # No recipe graph under the mock -> full cost minus gold in hand.
        assert _row_text(page, "gold") == f"{_KRAKEN_COST - _GOLD}g"
        # Stage mid at 15:00 with a yellow trinket held -> the free upgrade.
        assert _row_text(page, "trinket") == "Farsight Alteration"
        assert page.eval_on_selector(
            '#am-next-buy .nb-row[data-nb-row="trinket"]',
            "el => el.dataset.nbState") == "due"

        # ovx-widget field registration at its ambient default.
        assert page.eval_on_selector(
            "#am-next-buy", "e => e.classList.contains('ovx-widget')"
        ), "#am-next-buy is not an .ovx-widget"
        assert page.eval_on_selector(
            "#am-next-buy", "e => e.dataset.ovxId") == "w-nextbuy"
        assert _css(page, "#am-next-buy", "position") == "fixed"
        parent = page.eval_on_selector(
            "#am-next-buy", "e => e.parentElement.className")
        assert "am-grid" in parent, f"mount not an am-grid child: {parent!r}"

        # Value rows clear the 16px --fs-xs floor (game viewing distance);
        # the label column rides the 13px overlay chip token.
        val_fs = page.eval_on_selector(
            '#am-next-buy .nb-row[data-nb-row="gold"] .nb-v',
            "el => parseFloat(getComputedStyle(el).fontSize)")
        assert val_fs >= 16, f"value font {val_fs} below the 16px floor"
        key_fs = page.eval_on_selector(
            '#am-next-buy .nb-row[data-nb-row="gold"] .nb-k',
            "el => parseFloat(getComputedStyle(el).fontSize)")
        assert key_fs >= 13, f"label font {key_fs} below 13px"

        # Widen-to-fit: the longest real value ("Farsight Alteration") must
        # render in full, not ellipsised (measured regression 2026-07-23).
        assert page.eval_on_selector(
            '#am-next-buy .nb-row[data-nb-row="trinket"] .nb-v',
            "el => el.scrollWidth <= el.clientWidth + 1"), (
            "trinket value is clipped - widen w-nextbuy in overlay.css")

        SCRATCH.mkdir(exist_ok=True)
        page.locator("#am-next-buy").screenshot(
            path=str(SCRATCH / "next_buy_widget_sr.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [next-buy live sr]: {errors[:3]}"


def test_next_buy_does_not_reflow_when_the_rule_is_silent(
        mock_server, pw_browser):
    """NO REFLOW: a silent trinket rule renders the '-' sentinel in place -
    the row count and the widget box are unchanged."""
    ctx, page, errors = _open_live(pw_browser, mock_server, dict(_SR_STATE))
    try:
        _wait_rows(page)
        box_due = page.eval_on_selector(
            "#am-next-buy .nb-grid",
            "el => { const r = el.getBoundingClientRect();"
            " return [Math.round(r.width), Math.round(r.height)]; }")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [next-buy due]: {errors[:3]}"

    ctx, page, errors = _open_live(
        pw_browser, mock_server, dict(_SR_STATE_NO_TRINKET))
    try:
        _wait_rows(page)
        assert _row_text(page, "trinket") == "-"
        assert page.eval_on_selector(
            '#am-next-buy .nb-row[data-nb-row="trinket"]',
            "el => el.dataset.nbState || ''") == ""
        # Same three rows, same box: the sentinel holds the slot.
        assert page.eval_on_selector(
            "#am-next-buy", "el => el.querySelectorAll('.nb-row').length") == 3
        box_quiet = page.eval_on_selector(
            "#am-next-buy .nb-grid",
            "el => { const r = el.getBoundingClientRect();"
            " return [Math.round(r.width), Math.round(r.height)]; }")
        assert box_quiet[1] == box_due[1], (
            f"widget height moved {box_due} -> {box_quiet} (reflow)")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [next-buy quiet]: {errors[:3]}"


def test_next_buy_hidden_when_idle(mock_server, pw_browser):
    """HONEST NO-DATA: an empty envelope (no live game, no build path) keeps
    the widget hidden entirely - display none, no placeholder ghosts."""
    ctx, page, errors = _open_live(pw_browser, mock_server, {})
    try:
        page.wait_for_timeout(1500)
        assert page.eval_on_selector(
            "#am-next-buy", "el => el.hidden"), "widget must stay hidden idle"
        assert _css(page, "#am-next-buy", "display") == "none"
        assert page.eval_on_selector(
            "#am-next-buy", "el => el.querySelector('.nb-grid') === null"), (
            "no placeholder rows may render while idle")
        # Only the field drag handle overlay_layout.js injects may exist.
        assert page.eval_on_selector(
            "#am-next-buy",
            "el => [...el.children].every("
            "c => c.classList.contains('ovx-handle'))"), (
            "only the field drag handle may exist while idle")
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [next-buy idle]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text in this test file."""
    raw = Path(__file__).read_bytes()
    for bad in (b"\xe2\x80\x94", b"\xe2\x80\x93", b"\xe2\x80\x9c",
                b"\xe2\x80\x9d", b"\xe2\x80\x98", b"\xe2\x80\x99"):
        assert bad not in raw, f"non-ASCII punctuation {bad!r} in this file"
