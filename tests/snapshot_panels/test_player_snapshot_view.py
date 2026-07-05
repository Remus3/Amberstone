"""
tests/snapshot_panels/test_player_snapshot_view.py
Player-snapshot card VISUAL snapshot coverage (player-snapshot-card plan, Task 5).

renderPlayerSnapshot(el, model) (web/js/panels/player_snapshot.js +
web/css/panels/player_snapshot.css) is a pure presentational component: no
fetch, idempotent via a stashed JSON signature on el.dataset.sig. It is not
wired into any page mount yet (that lands in Task 6/7 Home/PGR adapters), so
this drives the component directly against a bare fixture div injected into
the mock server's page, exactly as test_player_gpi_view.py drives
showPlayerGpi() against a synthetic mount before its host wiring existed.

Three states are exercised: a full populated model (header/dial/minis/bars/
tags + the screenshot), a low-confidence model (same shape, thin sample), and
the empty model (reserved-height "-" sentinel card, no reflow).
"""
from pathlib import Path

SCREENSHOTS = Path(__file__).parent / "screenshots"

# Full populated model - mirrors the exact shape dashboard/routes_player_snapshot.py
# assembles (header/dial/minis/bars/tags/profile_ref/confidence/sample_n/empty).
_FULL_MODEL = {
    "header": {
        "name": "SamplePlayer", "rank_tier": "GOLD II", "rank_lp": 42,
        "level": 217, "streak": {"kind": "win", "n": 3},
        "champion_id": 222, "result": None,
    },
    "dial": {"value": 72, "band": "good", "label": "SR last 24h"},
    "minis": [
        {"key": "kda", "value": "3.45", "provenance": "source_truth"},
        {"key": "winrate", "value": "62%", "provenance": "source_truth"},
        {"key": "kp", "value": "58%", "provenance": "inferred"},
    ],
    "bars": [
        {"key": "income", "label": "INCOME", "score": 68.0, "provenance": "source_truth"},
        {"key": "combat", "label": "COMBAT", "score": 80.0, "provenance": "source_truth"},
        {"key": "objectives", "label": "OBJECTIVES", "score": 55.0, "provenance": "source_truth"},
        {"key": "vision", "label": "VISION", "score": 38.5, "provenance": "source_truth"},
    ],
    "tags": [
        {"label": "Aggressive", "tone": "strong"},
        {"label": "Generalist", "tone": "neutral"},
        {"label": "Visionless", "tone": "weak"},
    ],
    "profile_ref": {"mode": "sr", "window": "24h", "match_id": None},
    "confidence": "high", "sample_n": 20, "empty": False,
}

# Low-confidence model - same shape, thin sample; the card still renders (only
# an insufficient/zero-game window renders the empty state per the route's
# _build_snapshot_model contract).
_LOW_CONFIDENCE_MODEL = {
    "header": {
        "name": "SamplePlayer", "rank_tier": "GOLD II", "rank_lp": 42,
        "level": 217, "streak": {"kind": "loss", "n": 1},
        "champion_id": 64, "result": None,
    },
    "dial": {"value": 41, "band": "ok", "label": "SR last 24h"},
    "minis": [
        {"key": "kda", "value": "1.80", "provenance": "source_truth"},
        {"key": "winrate", "value": "33%", "provenance": "source_truth"},
        {"key": "kp", "value": "40%", "provenance": "inferred"},
    ],
    "bars": [
        {"key": "income", "label": "INCOME", "score": 45.0, "provenance": "source_truth"},
        {"key": "combat", "label": "COMBAT", "score": 39.0, "provenance": "source_truth"},
        {"key": "objectives", "label": "OBJECTIVES", "score": 30.0, "provenance": "source_truth"},
        {"key": "vision", "label": "VISION", "score": 25.0, "provenance": "source_truth"},
    ],
    "tags": [
        {"label": "Snowballer", "tone": "strong"},
        {"label": "Streaky", "tone": "neutral"},
        {"label": "Objective Shy", "tone": "weak"},
    ],
    "profile_ref": {"mode": "sr", "window": "24h", "match_id": None},
    "confidence": "low", "sample_n": 3, "empty": False,
}

# Empty model - exactly the shape dashboard/routes_player_snapshot.py's
# _build_snapshot_model returns on an insufficient/zero-game window.
_EMPTY_MODEL = {
    "header": {"name": None, "rank_tier": None, "rank_lp": None, "level": None,
               "streak": None, "champion_id": None, "result": None},
    "dial": {"value": 0, "band": "poor", "label": "No SR games in the last 24h"},
    "minis": [], "bars": [], "tags": [],
    "profile_ref": {"mode": "sr", "window": "24h", "match_id": None},
    "confidence": "insufficient", "sample_n": 0, "empty": True,
}


def _open_page(pw_browser, mock_server):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    from tests.snapshot_panels.conftest import _WS_STUB
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1", wait_until="domcontentloaded", timeout=15_000,
    )
    return ctx, page, errors


def _mount_and_render(page, model):
    """Create a bare #ps-fixture div and call renderPlayerSnapshot(el, model)."""
    page.evaluate(
        """async (model) => {
          let el = document.getElementById('ps-fixture');
          if (!el) {
            el = document.createElement('div');
            el.id = 'ps-fixture';
            document.body.appendChild(el);
          }
          const m = await import('/js/panels/player_snapshot.js');
          m.renderPlayerSnapshot(el, model);
        }""",
        model,
    )


def test_player_snapshot_full_model_renders(mock_server, pw_browser):
    ctx, page, errors = _open_page(pw_browser, mock_server)
    _mount_and_render(page, _FULL_MODEL)
    page.wait_for_selector('[data-testid="player-snapshot"]', timeout=10_000)
    try:
        root = page.locator('[data-testid="player-snapshot"]')
        assert root.is_visible(), "player-snapshot root not visible after render"

        # Dial band class drives the rendered data-band attribute.
        band = page.eval_on_selector(
            "#ps-fixture .ps-dial", "el => el.getAttribute('data-band')"
        )
        assert band == "good", f"dial band != good: {band!r}"

        dial_value = page.eval_on_selector(
            "#ps-fixture .ps-dial-value", "el => el.textContent.trim()"
        )
        assert dial_value == "72", f"dial value wrong: {dial_value!r}"

        # 4 bars, keyed income/combat/objectives/vision.
        bar_keys = page.eval_on_selector_all(
            "#ps-fixture .ps-bar[data-key]",
            "els => els.map(e => e.getAttribute('data-key'))",
        )
        assert set(bar_keys) == {"income", "combat", "objectives", "vision"}, bar_keys
        assert len(bar_keys) == 4, f"expected 4 bars, got {len(bar_keys)}"

        # 3 minis, keyed kda/winrate/kp.
        mini_keys = page.eval_on_selector_all(
            "#ps-fixture .ps-mini[data-key]",
            "els => els.map(e => e.getAttribute('data-key'))",
        )
        assert set(mini_keys) == {"kda", "winrate", "kp"}, mini_keys

        # 3 tags, [strong, neutral, weak] tones.
        tag_tones = page.eval_on_selector_all(
            "#ps-fixture .ps-tag[data-tone]",
            "els => els.map(e => e.getAttribute('data-tone'))",
        )
        assert tag_tones == ["strong", "neutral", "weak"], tag_tones

        # View Profile button present.
        vp = page.locator("#ps-fixture .ps-viewprofile")
        assert vp.count() == 1, "View Profile button missing"

        SCREENSHOTS.mkdir(exist_ok=True)
        root.screenshot(path=str(SCREENSHOTS / "player-snapshot_full.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_player_snapshot_low_confidence_model_renders(mock_server, pw_browser):
    ctx, page, errors = _open_page(pw_browser, mock_server)
    _mount_and_render(page, _LOW_CONFIDENCE_MODEL)
    page.wait_for_selector('[data-testid="player-snapshot"]', timeout=10_000)
    try:
        band = page.eval_on_selector(
            "#ps-fixture .ps-dial", "el => el.getAttribute('data-band')"
        )
        assert band == "ok", f"dial band != ok: {band!r}"

        bar_keys = page.eval_on_selector_all(
            "#ps-fixture .ps-bar[data-key]",
            "els => els.map(e => e.getAttribute('data-key'))",
        )
        assert len(bar_keys) == 4, f"expected 4 bars, got {len(bar_keys)}"

        tag_tones = page.eval_on_selector_all(
            "#ps-fixture .ps-tag[data-tone]",
            "els => els.map(e => e.getAttribute('data-tone'))",
        )
        assert len(tag_tones) == 3, f"expected 3 tags, got {len(tag_tones)}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_player_snapshot_empty_state_reserved_height(mock_server, pw_browser):
    ctx, page, errors = _open_page(pw_browser, mock_server)
    _mount_and_render(page, _EMPTY_MODEL)
    page.wait_for_selector('[data-testid="player-snapshot"]', timeout=10_000)
    try:
        # "-" sentinel + reserved-height card, no bars/minis/tags rendered.
        sentinel = page.eval_on_selector(
            "#ps-fixture .ps-sentinel", "el => el.textContent.trim()"
        )
        assert sentinel == "-", f"empty-state sentinel != '-': {sentinel!r}"

        msg = page.eval_on_selector(
            "#ps-fixture .ps-empty-msg", "el => el.textContent.trim()"
        )
        assert "No SR games" in msg, f"empty-state label wrong: {msg!r}"

        n_bars = page.eval_on_selector_all(
            "#ps-fixture .ps-bar", "els => els.length"
        )
        assert n_bars == 0, "no bars should render in the empty state"

        # Reserved height: the root's rendered height must be > 0 and stable -
        # asserting min-height is set (not display:none / collapsed to 0).
        box = page.eval_on_selector(
            '[data-testid="player-snapshot"]',
            "el => el.getBoundingClientRect().height",
        )
        assert box > 0, f"empty-state card collapsed to zero height: {box}"

        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator('[data-testid="player-snapshot"]').screenshot(
            path=str(SCREENSHOTS / "player-snapshot_empty.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_player_snapshot_idempotent_skip_on_unchanged_model(mock_server, pw_browser):
    """Re-rendering the same model object must not touch the DOM twice (the
    dataset.sig stash short-circuits) - proven by stamping a marker attribute
    on the root, then calling render again with an identical model and
    confirming the marker survives (a rebuild would wipe it via innerHTML)."""
    ctx, page, errors = _open_page(pw_browser, mock_server)
    _mount_and_render(page, _FULL_MODEL)
    page.wait_for_selector('[data-testid="player-snapshot"]', timeout=10_000)
    try:
        page.eval_on_selector(
            '[data-testid="player-snapshot"]',
            "el => el.setAttribute('data-marker', 'stamped')",
        )
        _mount_and_render(page, _FULL_MODEL)
        marker = page.eval_on_selector(
            '[data-testid="player-snapshot"]', "el => el.getAttribute('data-marker')"
        )
        assert marker == "stamped", "unchanged model triggered a DOM rebuild"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    targets = [
        Path(__file__),
        Path(__file__).parents[2] / "web" / "js" / "panels" / "player_snapshot.js",
        Path(__file__).parents[2] / "web" / "css" / "panels" / "player_snapshot.css",
    ]
    for p in targets:
        raw = p.read_bytes()
        offenders = [b for b in raw if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
