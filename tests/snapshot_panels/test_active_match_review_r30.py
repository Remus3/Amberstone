"""
tests/snapshot_panels/test_active_match_review_r30.py
R30 in-game design review - active-match MAP real-estate rethink.

Live Client exposes no champion coordinates (memory
reference_liveclient_no_positions), so the static map IMAGE can never plot
live positions - yet pre-R30 it dominated ~60% of the view with the high-
value live TEXT (the per-enemy MIA roster + vision status) crammed on top of
it as a 46%-max-width absolute overlay.

The rethink demotes the map image to a SECONDARY capped figure and promotes
the text: the MAP panel shell is restructured into
  .am-map-intel   (PRIMARY) -> #am-map-status + #am-map-roster, in flow
  .am-map-figure  (SECONDARY, max-height capped) -> #am-map-img + the
                   #am-map-overlay canvas + #am-map-gank band
All element IDs are preserved so the live polling / overlay / roster render
logic is unchanged. This guards: the new wrappers exist, the roster is no
longer an absolute overlay, and the map figure is height-capped (demoted).

Drive path mirrors test_active_match_view.py:
  /?ui_mock=1&mode=<mode>#active-match  (wait on the #am-sub InProgress stamp)
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCREENSHOTS = Path(__file__).parent / "screenshots"


def _open(pw_browser, mock_server, mode, w=1920, h=1080):
    from tests.snapshot_panels.conftest import _WS_STUB

    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": w, "height": h}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(
        mock_server.url + f"/?ui_mock=1&mode={mode}#active-match",
        wait_until="domcontentloaded", timeout=15_000,
    )
    page.wait_for_function(
        "document.querySelector('#am-sub') && "
        "document.querySelector('#am-sub').textContent.indexOf('InProgress') >= 0",
        timeout=10_000,
    )
    # Map shell builds on the active-match render; wait for it to attach.
    page.wait_for_function(
        "document.querySelector('#view-active-match .am-map-shell') !== null",
        timeout=8_000,
    )
    return ctx, page, errors


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_map_intel_promoted_over_figure(mode, mock_server, pw_browser):
    """The live text intel (status + roster) sits in a PRIMARY .am-map-intel
    region; the static map is a SECONDARY height-capped .am-map-figure. Both
    wrappers are new (pre-R30 the shell was a flat centered image with an
    absolute roster overlay)."""
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        r = page.evaluate(
            "() => {"
            " const root = '#view-active-match ';"
            " const intel = document.querySelector(root + '.am-map-intel');"
            " const fig = document.querySelector(root + '.am-map-figure');"
            " const status = document.getElementById('am-map-status');"
            " const roster = document.getElementById('am-map-roster');"
            " const img = document.getElementById('am-map-img');"
            " return {"
            "   hasIntel: !!intel, hasFig: !!fig,"
            "   statusInIntel: !!(intel && status && intel.contains(status)),"
            "   rosterInIntel: !!(intel && roster && intel.contains(roster)),"
            "   imgInFig: !!(fig && img && fig.contains(img)),"
            "   figMaxH: fig ? getComputedStyle(fig).maxHeight : 'none',"
            " }; }"
        )
        assert r["hasIntel"], f"{mode}: .am-map-intel wrapper missing"
        assert r["hasFig"], f"{mode}: .am-map-figure wrapper missing"
        assert r["statusInIntel"], f"{mode}: status not in the intel region"
        assert r["rosterInIntel"], f"{mode}: roster not in the intel region"
        assert r["imgInFig"], f"{mode}: map image not in the figure region"
        # The map figure must be height-capped (demoted), not free-filling.
        assert r["figMaxH"] not in ("none", ""), (
            f"{mode}: map figure not height-capped (maxHeight={r['figMaxH']!r})"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_roster_no_longer_absolute_overlay(mode, mock_server, pw_browser):
    """The per-enemy roster is promoted to in-flow text, not a cramped
    46%-max-width absolute overlay stamped on the dead map backdrop."""
    ctx, page, errors = _open(pw_browser, mock_server, mode)
    try:
        pos = page.eval_on_selector(
            "#am-map-roster", "el => getComputedStyle(el).position"
        )
        assert pos != "absolute", (
            f"{mode}: roster still an absolute overlay (position={pos})"
        )
        SCREENSHOTS.mkdir(exist_ok=True)
        page.locator("#view-active-match .am-pane-map").screenshot(
            path=str(SCREENSHOTS / f"active-match-r30_{mode}.png")
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode}]: {errors[:3]}"


# The widest VISIBLE right edge among all <header> descendants. The in-game
# header row 1 (champion / WIN / zone / clock / CS / vision + the right-pinned
# heartbeat) is no-wrap by desktop design; at the 923 companion width that row
# overflows and body{overflow:hidden} CLIPS the rightmost pills off-screen
# (lost data, not just a scrollbar). The fix is a companion (<=1200px) header
# reflow that keeps every pill on-screen.
_HEADER_WORST_RIGHT_JS = """() => {
  let worst = 0, sel = '';
  document.querySelectorAll('header *').forEach((el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return;
    const r = el.getBoundingClientRect();
    if (r.width >= 8 && r.right > worst) {
      worst = r.right; sel = el.id ? ('#' + el.id) : (el.className || el.tagName);
    }
  });
  return {worst: Math.round(worst), sel};
}"""


@pytest.mark.parametrize("mode", ["sr", "aram", "arena"])
def test_header_fits_companion_width(mode, mock_server, pw_browser):
    """In-game header must not clip at the 923 companion width: every visible
    header pill's right edge stays within the viewport (no off-screen
    heartbeat / vision pill). RED pre-fix (heartbeat overflowed to ~1226)."""
    ctx, page, errors = _open(pw_browser, mock_server, mode, w=923, h=1316)
    try:
        r = page.evaluate(_HEADER_WORST_RIGHT_JS)
        assert r["worst"] <= 924, (
            f"{mode}: header overflows the 923 companion viewport - "
            f"{r['sel']} right edge at {r['worst']}px (pills clipped off-screen)"
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{mode} companion]: {errors[:3]}"


def test_header_single_row_at_desktop(mock_server, pw_browser):
    """The companion reflow must NOT leak to the 1920 desktop: row-1 stays a
    single line (heartbeat vertically aligned with the CS pill) and nothing
    overflows the desktop viewport."""
    ctx, page, errors = _open(pw_browser, mock_server, "sr", w=1920, h=1080)
    try:
        r = page.evaluate(
            "() => {"
            " const hb = document.getElementById('heartbeat');"
            " const cs = document.getElementById('cs-pill');"
            " const worst = (" + _HEADER_WORST_RIGHT_JS + ")();"
            " return {"
            "   hbTop: hb ? Math.round(hb.getBoundingClientRect().top) : null,"
            "   csTop: cs ? Math.round(cs.getBoundingClientRect().top) : null,"
            "   worst: worst.worst,"
            " }; }"
        )
        assert r["hbTop"] is not None and r["csTop"] is not None
        assert abs(r["hbTop"] - r["csTop"]) <= 4, (
            f"row-1 wrapped at desktop: heartbeat top {r['hbTop']} vs "
            f"CS pill top {r['csTop']}"
        )
        assert r["worst"] <= 1921, f"header overflows 1920 desktop: {r['worst']}px"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [desktop]: {errors[:3]}"


def test_no_em_dashes_or_smart_quotes():
    """Hard rule: ASCII-only authored text - 0 bytes above 0x7F."""
    raw = Path(__file__).read_bytes()
    offenders = [b for b in raw if b > 0x7F]
    assert not offenders, f"non-ASCII byte(s): {offenders[:5]}"
