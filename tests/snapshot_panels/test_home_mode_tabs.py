"""
tests/snapshot_panels/test_home_mode_tabs.py
HOME mode-tab strip (SR/ARAM/ARENA filter) - FE half (2026-07-04).

Operator ruling (HOME_QA round-2): SR / ARAM / ARENA tabs so modes do not
taint each other's stats. The static strip (#home-mode-tabs, index.html)
sits between the hero and the quick-action tiles; main.js
_homeApplyModeTab syncs .active/aria-selected, persists the choice in
localStorage ("rc-home-mode-tab"), stamps the #home-overlay[data-mode-tab]
dataset hook, and refetches /api/home/summary?mode=<tab> (backend contract
d46ed74f: bad/absent mode = unfiltered; payload echoes mode_filter).

Drives the ui_mock home fixture through the mock-server + Playwright
harness (conftest.py), mirroring test_home_view.py. Under ui_mock the
refetch short-circuits to the mock fixture, so the dataset hook +
localStorage + active-state sync are the primary assertions here (the
?mode= URL itself is exercised by the backend's own route tests).

Also pins the R30 momentum-verdict KDA-trend fallback: an empty
last20.results (the ARAM tab's last20 = {} policy until rewind gains
Mayhem rows) must fall through to the 14-day KDA trend branch, never
crash or read "Ready when you are" while trend data exists.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"
FIXTURE = ROOT / "web" / "data" / "ui_mock" / "home.json"

# The startup apply (_homeWireStartup -> _homeApplyModeTab) stamps the
# overlay dataset hook - the tabs-wired settled signal.
_TABS_READY = (
    "document.getElementById('home-overlay') && "
    "!!document.getElementById('home-overlay').dataset.modeTab"
)
_PICK_READY = (
    "document.querySelector('#home-coach-pick-champ') && "
    "document.querySelector('#home-coach-pick-champ').textContent.trim() "
    "!== '-' && "
    "document.querySelector('#home-coach-pick-champ').textContent.trim() "
    "!== ''"
)


def _open_home(pw_browser, mock_server, w=1920, h=1080, settle=_TABS_READY):
    from tests.snapshot_panels.conftest import _WS_STUB

    # Empty SSE state -> main.js auto-derive resolves to "home" (mode
    # client / no liveclient), so the home view wins the router.
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(
        mock_server.url + "/?ui_mock=1#home",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(settle, timeout=10_000)
    return ctx, page, errors


def _tab_state(page):
    return page.evaluate(
        """() => {
          const out = {};
          document.querySelectorAll('.home-mode-tab').forEach(btn => {
            out[btn.dataset.hmode] = {
              active: btn.classList.contains('active'),
              selected: btn.getAttribute('aria-selected'),
            };
          });
          out._dataset =
            document.getElementById('home-overlay').dataset.modeTab || '';
          out._stored = localStorage.getItem('rc-home-mode-tab');
          return out;
        }"""
    )


def test_home_mode_tabs_render_with_hit_targets(mock_server, pw_browser):
    """(a) 4 tabs render inside the tablist strip, each clearing the 44px
    hit-target floor (min-height: max(var(--hit-min), 44px))."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        strip = page.locator("#home-mode-tabs")
        assert strip.is_visible(), "#home-mode-tabs strip not visible"
        assert strip.get_attribute("role") == "tablist", (
            "mode-tab strip missing role=tablist"
        )
        tabs = page.locator("#home-mode-tabs .home-mode-tab")
        assert tabs.count() == 4, (
            f"expected 4 mode tabs (ALL/SR/ARAM/ARENA), got {tabs.count()}"
        )
        for n in range(4):
            box = tabs.nth(n).bounding_box()
            assert box is not None and box["height"] >= 44, (
                f"mode tab #{n} height "
                f"{box and box['height']} below the 44px hit floor"
            )
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#home-mode-tabs").screenshot(
            path=str(SCREENSHOTS / "home_mode-tabs.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [mode tabs render]: {errors[:3]}"


def test_home_mode_tabs_default_all(mock_server, pw_browser):
    """(b) A fresh browser (no persisted choice) lands on ALL: .active +
    aria-selected=true on ALL, the other three unselected, and the overlay
    dataset hook reads ALL."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        st = _tab_state(page)
        assert st["_dataset"] == "ALL", (
            f"overlay dataset hook {st['_dataset']!r} != 'ALL'"
        )
        assert st["ALL"]["active"] and st["ALL"]["selected"] == "true", (
            f"ALL tab not the default active: {st['ALL']!r}"
        )
        for mode in ("SR", "ARAM", "ARENA"):
            assert not st[mode]["active"], f"{mode} tab active by default"
            assert st[mode]["selected"] == "false", (
                f"{mode} tab aria-selected {st[mode]['selected']!r}"
            )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [mode tabs default]: {errors[:3]}"


def test_home_mode_tab_click_applies_aram(mock_server, pw_browser):
    """(c) Clicking the ARAM tab moves the filter: dataset hook + persisted
    localStorage + active/aria-selected all flip to ARAM (the dataset hook
    is the re-render-attempt signal; under ui_mock the refetch
    short-circuits to the fixture, so no network assertion here)."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        page.locator('.home-mode-tab[data-hmode="ARAM"]').click()
        page.wait_for_function(
            "document.getElementById('home-overlay').dataset.modeTab "
            "=== 'ARAM'",
            timeout=5_000,
        )
        st = _tab_state(page)
        assert st["_dataset"] == "ARAM", (
            f"overlay dataset hook {st['_dataset']!r} != 'ARAM'"
        )
        assert st["_stored"] == "ARAM", (
            f"localStorage rc-home-mode-tab {st['_stored']!r} != 'ARAM'"
        )
        assert st["ARAM"]["active"] and st["ARAM"]["selected"] == "true", (
            f"ARAM tab not active after click: {st['ARAM']!r}"
        )
        assert not st["ALL"]["active"], "ALL tab still active after ARAM"
        assert st["ALL"]["selected"] == "false", (
            f"ALL aria-selected {st['ALL']['selected']!r} after ARAM click"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [mode tab click]: {errors[:3]}"


def test_home_mode_tab_persists_across_reload(mock_server, pw_browser):
    """(d) The persisted choice restores on load: click ARAM, reload, and
    the startup apply (_homeWireStartup) lands back on ARAM."""
    ctx, page, errors = _open_home(pw_browser, mock_server)
    try:
        page.locator('.home-mode-tab[data-hmode="ARAM"]').click()
        page.wait_for_function(
            "document.getElementById('home-overlay').dataset.modeTab "
            "=== 'ARAM'",
            timeout=5_000,
        )
        page.reload(wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "document.getElementById('home-overlay') && "
            "document.getElementById('home-overlay').dataset.modeTab "
            "=== 'ARAM'",
            timeout=10_000,
        )
        st = _tab_state(page)
        assert st["ARAM"]["active"] and st["ARAM"]["selected"] == "true", (
            f"persisted ARAM tab not restored after reload: {st['ARAM']!r}"
        )
        assert not st["ALL"]["active"], "ALL re-activated after reload"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [mode tab persist]: {errors[:3]}"


def test_home_mode_tabs_between_hero_and_pick(mock_server, pw_browser):
    """(e) Geometry pin (mirrors the companion heroAbovePick pattern): the
    tab strip sits BELOW the hero and ABOVE the Tonight's Pick card."""
    ctx, page, errors = _open_home(
        pw_browser, mock_server, settle=_PICK_READY
    )
    try:
        geo = page.evaluate(
            """() => {
              const hero = document.querySelector('.home-hero');
              const tabs = document.querySelector('#home-mode-tabs');
              const pick = document.querySelector('#home-coach-pick');
              if (!hero || !tabs || !pick) return null;
              const h = hero.getBoundingClientRect();
              const t = tabs.getBoundingClientRect();
              const p = pick.getBoundingClientRect();
              return {
                tabsBelowHero: t.top >= h.bottom - 1,
                tabsAbovePick: t.bottom <= p.top + 1,
              };
            }"""
        )
        assert geo, "hero / mode-tabs / pick element missing"
        assert geo["tabsBelowHero"], "mode-tab strip not below the hero"
        assert geo["tabsAbovePick"], (
            "mode-tab strip not above the Tonight's Pick card"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [mode tabs geometry]: {errors[:3]}"


def test_home_mode_tabs_equal_tracks_both_widths(mock_server, pw_browser):
    """(f) The strip is a 4-equal-column grid at BOTH the 920 companion and
    the 1920 desktop widths (no media-query reflow; 4 tracks fit 920)."""
    for w, h in ((920, 1280), (1920, 1080)):
        ctx, page, errors = _open_home(pw_browser, mock_server, w=w, h=h)
        try:
            cols = page.evaluate(
                "getComputedStyle("
                "document.querySelector('#home-mode-tabs'))"
                ".gridTemplateColumns"
            )
            tracks = [float(v.replace("px", "")) for v in cols.split()]
            assert len(tracks) == 4, (
                f"expected 4 grid tracks at {w}px, got {cols!r}"
            )
            assert max(tracks) - min(tracks) <= 1.5, (
                f"mode-tab tracks unequal at {w}px: {cols!r}"
            )
        finally:
            page.close()
            ctx.close()
        assert not errors, f"JS errors [mode tabs {w}px]: {errors[:3]}"


def test_home_momentum_falls_back_to_kda_trend(mock_server, pw_browser):
    """R30 fallback pin: with an idle day (games=0) and an EMPTY
    last20.results (the ARAM-tab last20 = {} policy until rewind gains
    Mayhem rows), _homeMomentumVerdict skips the last-5 W/L branch and
    falls back to the 14-day KDA trend verdict - never the decorative
    greeting while trend data exists. Injected via page.route so the
    shared fixture stays intact (test_home_review_r30.py pattern)."""
    from tests.snapshot_panels.conftest import _WS_STUB

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["today"] = {
        "games": 0, "total_kda": "0/0/0", "avg_kda": None,
        "grades": {}, "modes": {},
    }
    payload["last20"] = {
        "results": [], "wins": 0, "losses": 0, "win_rate": 0,
    }
    body = json.dumps(payload)

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def _fulfill(r):
        r.fulfill(status=200, content_type="application/json", body=body)
    page.route("**/data/ui_mock/home.json", _fulfill)
    page.route("**/api/home/summary", _fulfill)
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1#home",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(_PICK_READY, timeout=10_000)
        headline = page.locator("#home-hero-headline")
        txt = (headline.text_content() or "").strip()
        assert txt != "Ready when you are", (
            "empty last20.results fell to the greeting, not the KDA trend"
        )
        assert "last 5" not in txt.lower(), (
            f"empty last20.results still hit the W/L branch: {txt!r}"
        )
        assert "kda" in txt.lower(), (
            f"idle headline is not the KDA-trend fallback verdict: {txt!r}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [momentum fallback]: {errors[:3]}"


def test_home_wl_strip_reserves_slot_on_filtered_tab(
    mock_server, pw_browser
):
    """Operator ruling (round 2): a mode tab whose last20 the backend
    filtered to empty (ARAM until rewind gains Mayhem rows) RESERVES the
    pip strip's vertical slot (.is-reserved: visibility hidden, height
    kept) so the hero does not jump between tabs - while the no-data ALL
    tab still collapses the row entirely ([hidden]). Same route-injection
    pattern as the momentum-fallback test above."""
    from tests.snapshot_panels.conftest import _WS_STUB

    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["last20"] = {
        "results": [], "wins": 0, "losses": 0, "win_rate": 0,
    }
    body = json.dumps(payload)

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 920, "height": 1280}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    def _fulfill(r):
        r.fulfill(status=200, content_type="application/json", body=body)
    page.route("**/data/ui_mock/home.json", _fulfill)
    page.route("**/api/home/summary", _fulfill)
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1#home",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(_TABS_READY, timeout=10_000)

        def _wl_state():
            return page.evaluate(
                """() => {
                  const el =
                    document.getElementById('home-hero-rank-wl');
                  const r = el.getBoundingClientRect();
                  return {
                    hidden: el.hidden,
                    reserved: el.classList.contains('is-reserved'),
                    visibility: getComputedStyle(el).visibility,
                    height: r.height,
                  };
                }"""
            )

        # ALL tab + no W/L data at all -> fully collapsed, no ghost band.
        st = _wl_state()
        assert st["hidden"] and not st["reserved"], (
            f"ALL-tab empty strip should collapse via [hidden]: {st!r}"
        )

        # ARAM tab (filter-empty) -> slot reserved, invisible, height kept.
        page.locator('.home-mode-tab[data-hmode="ARAM"]').click()
        page.wait_for_function(
            "document.getElementById('home-hero-rank-wl')"
            ".classList.contains('is-reserved')",
            timeout=5_000,
        )
        st = _wl_state()
        assert not st["hidden"], (
            f"filtered-tab strip must keep its box (not [hidden]): {st!r}"
        )
        assert st["visibility"] == "hidden", (
            f"filtered-tab strip should be visibility:hidden: {st!r}"
        )
        assert st["height"] >= 16, (
            f"reserved strip lost its vertical slot ({st['height']}px)"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [wl strip reserve]: {errors[:3]}"


def test_home_headline_one_line_no_reflow_contract(mock_server, pw_browser):
    """Round-2 no-reflow: the momentum headline is ONE line always -
    nowrap + ellipsis (a long trend verdict must not wrap and grow the
    hero, which shifted every card below on the ARAM tab) - and a hidden
    headline (1-2 games today) keeps its line box (visibility-hidden
    reserve), so all tabs share one hero height."""
    ctx, page, errors = _open_home(pw_browser, mock_server, w=920, h=1280)
    try:
        st = page.evaluate(
            """() => {
              const h = document.getElementById('home-hero-headline');
              const cs = getComputedStyle(h);
              return {
                nowrap: cs.whiteSpace,
                overflow: cs.overflow,
                ellipsis: cs.textOverflow,
              };
            }"""
        )
        assert st["nowrap"] == "nowrap", (
            f"headline may wrap (white-space {st['nowrap']!r})"
        )
        assert st["ellipsis"] == "ellipsis", (
            f"headline missing the ellipsis backstop: {st['ellipsis']!r}"
        )
        # Hidden state keeps the slot: set [hidden] and confirm the line
        # box survives with visibility:hidden instead of display:none.
        reserved = page.evaluate(
            """() => {
              const h = document.getElementById('home-hero-headline');
              h.hidden = true;
              const cs = getComputedStyle(h);
              const r = h.getBoundingClientRect();
              const out = {display: cs.display, visibility: cs.visibility,
                           height: r.height};
              h.hidden = false;
              return out;
            }"""
        )
        assert reserved["display"] != "none", (
            f"[hidden] headline collapsed (display {reserved['display']!r})"
        )
        assert reserved["visibility"] == "hidden", (
            f"[hidden] headline still visible: {reserved!r}"
        )
        assert reserved["height"] >= 20, (
            f"[hidden] headline lost its line box: {reserved['height']}px"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [headline contract]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F in this
    test file (the fixture is covered by the sibling view tests)."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
