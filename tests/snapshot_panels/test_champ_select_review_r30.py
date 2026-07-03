"""
tests/snapshot_panels/test_champ_select_review_r30.py
R30 in-game design review - ARAM + Arena champ-select ASSESSMENT + layout.

Two coupled defects this pins:

  PART B (content) - the ASSESSMENT (suggestions) card was SR-only: in
  ARAM/Arena the right column rendered EMPTY because the suggestion
  renderers (counter-picks / team-damage / cooldown-watch) were gated to
  mode==="sr" (champ_select.js ~774). counter-picks is an SR-DRAFT concept
  (no counter-draft in ARAM/Arena), but the team-damage lean (own roster
  AD/AP balance) and watch-their-cooldowns (enemy hard-CC timers) read off
  ANY roster, so they now render in non-SR too.

  PART A (layout) - the non-SR grid override dropped the "suggestions"
  grid-area (champ_select_view.css ~1792), so .csv-card-suggestions was
  ORPHANED out of grid flow: it floated as a disconnected block and left a
  large vertical void (worst in Arena). The fix gives ARAM/Arena a 2-row
  grid with the suggestions card back under Enemies in the right column.

Drive path mirrors test_champ_select_view.py:
  /?ui_mock=1&mode=<aram|arena>#champ-select
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"

# Per-mode central-pane marker that proves the async mock render landed
# (so the suggestions pass at champ_select.js:774 has also fired).
_MODE_CONTENT = {
    "aram": ".csv-bench-cell",
    "arena": ".csv-duo-cell",
}


def _open(pw_browser, mock_server, mode):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    # team-damage lives inside the TEAM ANALYSIS cluster (QA 2026-07-03 B18),
    # collapsed by default; seed the sanctioned open key so visibility
    # assertions see the expanded state.
    page.add_init_script("sessionStorage.setItem('csv-ta-open', '1');")
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    url = mock_server.url + f"/?ui_mock=1&mode={mode}#champ-select"
    page.goto(url, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        f"document.querySelectorAll('#view-champ-select {_MODE_CONTENT[mode]}')"
        ".length > 0",
        timeout=10_000,
    )
    return ctx, page, errors


@pytest.mark.parametrize("mode", ["aram", "arena"])
def test_assessment_renders_team_damage(mode, mock_server, pw_browser):
    """ARAM/Arena ASSESSMENT surfaces the team-damage lean. The box is
    `hidden` by default and was never rendered in non-SR before the fix;
    now it shows the TEAM DAMAGE LEAN head off the own roster."""
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        page.wait_for_function(
            "(() => { const b = document.getElementById('csv-sugg-team-damage');"
            " return b && !b.hidden"
            " && b.textContent.indexOf('TEAM DAMAGE LEAN') >= 0; })()",
            timeout=8_000,
        )
        assert page.locator("#csv-sugg-team-damage").is_visible(), (
            f"team-damage card hidden in {mode}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["aram", "arena"])
def test_counter_picks_stays_sr_only(mode, mock_server, pw_browser):
    """counter-picks is an SR-draft concept - it must NOT surface in
    ARAM/Arena (no counter-draft there)."""
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        cp = page.locator("#csv-sugg-counter-picks")
        assert not cp.is_visible(), (
            f"counter-picks should stay hidden in {mode}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["aram", "arena"])
def test_assessment_card_in_right_column(mode, mock_server, pw_browser):
    """The ASSESSMENT card sits IN the grid under Enemies (right column),
    not orphaned as a floating/auto-placed block."""
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        # Let the suggestions pass + any reflow settle.
        page.wait_for_function(
            "(() => { const b = document.getElementById('csv-sugg-team-damage');"
            " return b && !b.hidden; })()",
            timeout=8_000,
        )
        r = page.evaluate(
            "() => {"
            " const root = '#view-champ-select ';"
            " const s = document.querySelector(root + '.csv-card-suggestions');"
            " const e = document.querySelector(root + '.csv-card-enemies');"
            " const vw = document.documentElement.clientWidth;"
            " const box = (el) => { const b = el.getBoundingClientRect();"
            "   return {left: b.left, right: b.right, top: b.top,"
            "           bottom: b.bottom, h: b.height}; };"
            " return {s: box(s), e: box(e), vw}; }"
        )
        s, e, vw = r["s"], r["e"], r["vw"]
        assert s["h"] > 20, f"suggestions card collapsed in {mode}: h={s['h']}"
        # Right column: the suggestions card lives in the right third.
        assert s["left"] > vw * 0.6, (
            f"suggestions not in right column ({mode}):"
            f" left={s['left']} vw={vw}"
        )
        # Stacked under Enemies, left edges column-aligned (same grid track).
        assert s["top"] >= e["bottom"] - 8, (
            f"suggestions not below enemies ({mode}):"
            f" s.top={s['top']} e.bottom={e['bottom']}"
        )
        assert abs(s["left"] - e["left"]) < 12, (
            f"suggestions not column-aligned with enemies ({mode}):"
            f" s.left={s['left']} e.left={e['left']}"
        )
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-champ-select").screenshot(
            path=str(SCREENSHOTS / f"champ-select-r30_{mode}.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


def test_arena_renders_archetype_picker(mock_server, pw_browser):
    """Arena gets the DS archetype picker in the left column. Pre-fix an
    early-return in _csvRenderCentralPane skipped the archetype render for
    Arena (left column stuck on 'waiting for champion pick...') even though
    the fixture carries my_champion=222 + build_variants['Jinx|arena']."""
    ctx, page, errors = _open(pw_browser, mock_server, "arena")
    try:
        page.wait_for_function(
            "document.querySelectorAll("
            "'#csv-archetype-target .csv-arch-btn').length > 0",
            timeout=8_000,
        )
        btns = page.locator("#csv-archetype-target .csv-arch-btn")
        assert btns.count() >= 6, (
            f"expected 6 archetype buttons in Arena, got {btns.count()}"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [arena archetype]: {errors[:3]}"


def test_arena_renders_build_chooser(mock_server, pw_browser):
    """Arena gets the build chooser (titled 'Arena build chooser') in the
    My Pick pane ALONGSIDE the existing duo + augments (no regression)."""
    ctx, page, errors = _open(pw_browser, mock_server, "arena")
    try:
        page.wait_for_function(
            "(() => { const b = document.querySelector("
            "'#view-champ-select .csv-card-mypick .csv-builds');"
            " return b && b.textContent.indexOf('Arena build chooser') >= 0;"
            " })()",
            timeout=8_000,
        )
        # Duo + augments must survive the build-chooser addition.
        assert page.locator("#view-champ-select .csv-duo-cell").count() > 0, (
            "Arena duo cells lost"
        )
        assert page.locator(
            "#view-champ-select .csv-augment-slot"
        ).count() > 0, "Arena augment slots lost"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [arena build]: {errors[:3]}"


def _grid_track_count(page):
    return page.evaluate(
        "() => { const e = document.querySelector("
        "'#view-champ-select .csv-grid');"
        " if (!e) return null;"
        " const g = getComputedStyle(e).gridTemplateColumns;"
        " return (g || '').trim().split(/\\s+/).filter(Boolean).length; }"
    )


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_companion_single_column_reflow(mode, mock_server, pw_browser):
    """Champ-select collapses to ONE column at the ~923 rc-shell companion
    width (mirrors the out-of-game item-602 reflow) and keeps the 3-column
    layout on the 1920 desktop. The pre-R30 grid stayed 3-col at 923 and
    crushed/clipped."""
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    for (w, h, want) in [(923, 1316, 1), (1920, 1080, 3)]:
        ctx = pw_browser.new_context(
            ignore_https_errors=True, viewport={"width": w, "height": h}
        )
        page = ctx.new_page()
        page.add_init_script(_WS_STUB)
        errors: list[str] = []
        page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode={mode}#champ-select",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "document.querySelector('#view-champ-select .csv-grid') !== null",
            timeout=10_000,
        )
        tracks = _grid_track_count(page)
        page.close()
        ctx.close()
        assert tracks == want, (
            f"{mode} at {w}px: expected {want} grid track(s), got {tracks}"
        )
        assert not errors, f"JS errors [{mode} {w}px]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
