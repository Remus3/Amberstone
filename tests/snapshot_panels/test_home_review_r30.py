"""
tests/snapshot_panels/test_home_review_r30.py
HOME per-page design-review regressions (R30, 2026-06-23).

Pins the keep/remove/add/alter changes from the slow per-page UI/UX review of
the Home view:
  - the play-streak is NOT duplicated inside Tonight's Pick (it shows only in
    the hero identity sub-line);
  - Tonight's Pick Section 3 (Advisories) hides entirely when there is no open
    advisory - no "Advisories: None" noise;
  - all three hero stat chips read ONE consistent 14-day-latest timeframe
    (KDA is no longer driven by today's "0/0/0" triple);
  - the idle (0-games) headline is a recent-form momentum verdict, not the
    decorative "Ready when you are" greeting;
  - a primary Find Match CTA sits in the hero and opens the queue picker;
  - small-sample (1-2 game) Good/Bad tip rows are hidden, not shown as "-".

Drives the ui_mock home fixture through the mock-server + Playwright harness
(conftest.py). The idle + small-sample states are injected with page.route so
the shared played-day fixture stays intact for the sibling view tests.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"
FIXTURE = ROOT / "web" / "data" / "ui_mock" / "home.json"

_PICK_READY = (
    "document.querySelector('#home-coach-pick-champ') && "
    "document.querySelector('#home-coach-pick-champ').textContent.trim() "
    "!== '-' && "
    "document.querySelector('#home-coach-pick-champ').textContent.trim() "
    "!== ''"
)


def _ctx(pw_browser, w=1920, h=1080):
    from tests.snapshot_panels.conftest import _WS_STUB
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    return ctx, page, errors


def _open(page, mock_server, route_payload=None):
    # Home fetches twice at boot: the ui_mock load (/data/ui_mock/home.json)
    # and a follow-up /api/home/summary (which the conftest mock_server answers
    # with {} - a harness-only quirk; live returns real data, so the second
    # pass clobbers the rendered state to empty in-harness). Route BOTH paths to
    # the SAME payload so neither pass clobbers, matching live where both
    # fetches return identical data. Default payload = the real fixture.
    if route_payload is None:
        route_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    body = json.dumps(route_payload)

    def _fulfill(r):
        r.fulfill(status=200, content_type="application/json", body=body)
    page.route("**/data/ui_mock/home.json", _fulfill)
    page.route("**/api/home/summary", _fulfill)
    mock_server._store["data"] = {}
    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(_PICK_READY, timeout=10_000)


def test_no_duplicate_streak_in_tonight_pick(mock_server, pw_browser):
    ctx, page, errors = _ctx(pw_browser)
    try:
        _open(page, mock_server)
        pick_txt = (page.locator("#home-coach-pick").inner_text() or "").lower()
        assert "play streak" not in pick_txt, (
            f"play-streak duplicated inside Tonight's Pick: {pick_txt!r}"
        )
        assert "s/a in a row" not in pick_txt, (
            f"S/A streak duplicated inside Tonight's Pick: {pick_txt!r}"
        )
        # The streak still shows in the hero identity sub-line (the one home).
        sub = (page.locator("#home-hero-sub").text_content() or "").lower()
        assert "streak" in sub or "s/a" in sub, (
            f"streak missing from the hero sub-line: {sub!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_advisories_section_hidden_when_empty(mock_server, pw_browser):
    ctx, page, errors = _ctx(pw_browser)
    try:
        _open(page, mock_server)
        sec3 = page.locator("#home-pick-section-3")
        assert sec3.count() == 1, "Tonight's Pick Section 3 missing"
        n = int(
            (page.locator("#advisory-count").text_content() or "0").strip()
            or "0"
        )
        # Section 3 is visible iff there is at least one open advisory.
        assert sec3.is_visible() == (n > 0), (
            f"advisories section visibility {sec3.is_visible()} != (count {n} "
            f"> 0); an empty 'Advisories: None' row must not render"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_chips_consistent_14d_timeframe(mock_server, pw_browser):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    kda_latest = [
        p["value"] for p in fixture["trends"]["kda"] if p["value"] is not None
    ][-1]
    ctx, page, errors = _ctx(pw_browser)
    try:
        _open(page, mock_server)
        kda = (page.locator("#home-hero-kda").text_content() or "").strip()
        # KDA chip now reads the 14d trend latest (e.g. "5.6"), one timeframe
        # with CS/GOLD - NOT today's "32/14/47" K/D/A triple.
        assert kda == f"{kda_latest:.1f}", (
            f"KDA chip {kda!r} != trend latest {kda_latest:.1f}"
        )
        assert "/" not in kda, f"KDA chip still a today K/D/A triple: {kda!r}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_hero_find_match_cta_opens_picker(mock_server, pw_browser):
    ctx, page, errors = _ctx(pw_browser)
    try:
        _open(page, mock_server)
        cta = page.locator("#home-hero-cta")
        assert cta.is_visible(), "hero Find Match CTA not visible"
        picker = page.locator("#home-find-match-picker")
        assert "hidden" in (picker.get_attribute("class") or ""), (
            "queue picker should start hidden"
        )
        cta.click()
        page.wait_for_function(
            "!document.querySelector('#home-find-match-picker')"
            ".classList.contains('hidden')",
            timeout=3_000,
        )
        assert "hidden" not in (picker.get_attribute("class") or ""), (
            "Find Match CTA did not open the queue picker"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_idle_headline_is_momentum_verdict(mock_server, pw_browser):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = dict(fixture)
    payload["today"] = {
        "games": 0, "total_kda": "0/0/0", "avg_kda": None,
        "grades": {}, "modes": {},
    }
    # newest-first: L,L,L,L,W -> 1 win in the last 5 -> "Rough patch" (.down).
    payload["last20"] = {
        "results": ["L", "L", "L", "L", "W", "W", "W", "W", "W", "W"],
        "wins": 6, "losses": 4, "win_rate": 60.0,
    }
    ctx, page, errors = _ctx(pw_browser)
    try:
        _open(page, mock_server, route_payload=payload)
        headline = page.locator("#home-hero-headline")
        txt = (headline.text_content() or "").strip()
        assert txt != "Ready when you are", (
            "idle headline is still the decorative greeting, not a verdict"
        )
        assert "last 5" in txt.lower(), (
            f"idle headline is not a recent-form W/L verdict: {txt!r}"
        )
        cls = headline.get_attribute("class") or ""
        assert "down" in cls, (
            f"expected the .down momentum colour for 1W-in-5: {cls!r} / {txt!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_small_sample_good_bad_rows_hidden(mock_server, pw_browser):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload = dict(fixture)
    tp = dict(fixture["tonight_pick"])
    # Backend suppresses Good + Bad at a 1-2 game sample (empty strings).
    tp["tips"] = {
        "good": "", "bad": "",
        "ugly": "Small sample - 1 game, play more for tips",
    }
    payload["tonight_pick"] = tp
    ctx, page, errors = _ctx(pw_browser)
    try:
        _open(page, mock_server, route_payload=payload)
        hidden = page.evaluate(
            """() => {
              const row = id => {
                const el = document.querySelector('#' + id);
                const r = el && el.closest('.home-pick-tip-row');
                return r ? r.hidden : null;
              };
              return {good: row('home-pick-good'), bad: row('home-pick-bad'),
                      ugly: row('home-pick-ugly')};
            }"""
        )
        assert hidden["good"] is True, "small-sample Good row not hidden"
        assert hidden["bad"] is True, "small-sample Bad row not hidden"
        assert hidden["ugly"] is False, "Ugly caveat row must stay visible"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_full_sample_tips_render(mock_server, pw_browser):
    """The played-day fixture (6-game pick) shows all three populated tip
    rows - proves the fixture's nested `tips` shape matches production and the
    row-hide logic does not over-hide."""
    ctx, page, errors = _ctx(pw_browser)
    try:
        _open(page, mock_server)
        good = (page.locator("#home-pick-good").text_content() or "").strip()
        assert good and good != "-", f"Good tip not rendered: {good!r}"
        assert "avg KDA" in good, f"Good tip not the backend shape: {good!r}"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#home-overlay").screenshot(
            path=str(SCREENSHOTS / "home_r30.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only in this slice's authored test + the fixture."""
    for p in (Path(__file__), FIXTURE):
        offenders = [b for b in p.read_bytes() if b > 0x7F]
        assert not offenders, f"non-ASCII byte(s) in {p}: {offenders[:5]}"
