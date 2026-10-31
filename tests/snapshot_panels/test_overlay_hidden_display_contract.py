"""
tests/snapshot_panels/test_overlay_hidden_display_contract.py
RM-1207 (s144 uiux): the RM-1206 contract "a hidden element must not
render" on the in-game overlay shell (?overlay=1), which the dashboard sweep
in test_hidden_display_contract.py never loads.

The overlay is a different cascade: web/css/overlay.css plus the TFT widget
CSS that web/js/lib/overlay_tft.js injects at runtime (TFT_OVERLAY_CSS), and
its hide sites are JS-only. An author `display` on a hidden element beats the
UA `[hidden] { display: none }` rule, so it keeps painting in-game.

Measured in headless Chromium, 2026-10-31, before this guard: in sr / aram /
arena (?ui_mock=1) and tft (the live tft_overlay_feed envelope) every element
the overlay marks hidden computes display:none, apart from the two deliberate
exceptions the dashboard guard already names. No live defect; this file pins
it. Forcing `hidden` on every id'd overlay element showed which mounts WOULD
still paint (w-launcher, the CALL / BUILD panes, #aram-balance-panel, the
#ovset rows): none of them is ever hidden by the `hidden` attribute (the
per-widget gate is .ovx-hidden, #aram-balance-panel uses an inline style), so
they are not in scope. The overlay's own hide sites:
- lib/overlay_tft.js builds its mounts at runtime, so web/index.html does not
  declare them: every .ovt-panel mount is created hidden and data-gated
  (w-tft-lobby stays hidden until lobby rows arrive), and each of the 12 unit
  chips carries 3 star pips, hidden beyond its star level. The pips only
  collapse through the injected `.ovt-stars > i[hidden] { display: none; }`
  rule, because the base pip rule sets display:block. These are forced hidden
  in the sweep (_FORCED) even while they show.
- #am-pane-ovds (panels/overlay_ds_controls.js) and #rn-lead / #rn-choices /
  #rn-callouts (overlay.css shows them on a :not([hidden]) rule) are declared
  hidden in web/index.html, so the shared static-id sweep already forces them.
"""
import json
import re
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_hidden_display_contract import (
    _EXCEPTIONS,
    _SWEEP,
    _static_hidden_ids,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
VP = {"width": 1920, "height": 1080}

# Runtime-built overlay mounts whose renderer toggles the `hidden` attribute.
# Each must still name a real hide site (test_forced_sites_are_real).
_FORCED = (
    ".ovt-panel",
    ".ovt-stars > i",
)
# Overlay hide sites declared hidden in web/index.html (static-id sweep).
_STATIC_OVERLAY = ("am-pane-ovds", "rn-lead", "rn-choices", "rn-callouts")

# _SWEEP checks every [hidden] element plus a list of ids. Extend it with the
# forced selectors: their elements are collected and handed over as a marker
# attribute, so the shared sweep body stays the one source of the contract.
_MARK = """
(sels) => {
  let n = 0;
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) {
      if (!el.id) { el.id = 'ovhd-forced-' + (n++); el.dataset.ovhdTmp = '1'; }
    }
  }
  const ids = [];
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) ids.push(el.id);
  }
  return ids;
}
"""

_UNMARK = """
() => { for (const el of document.querySelectorAll('[data-ovhd-tmp]')) {
  el.removeAttribute('id'); el.removeAttribute('data-ovhd-tmp'); } }
"""


def _open(pw_browser, mock_server, query, data=None):
    mock_server._store["data"] = data or {}
    ctx = pw_browser.new_context(ignore_https_errors=True, viewport=VP)
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/" + query,
              wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.body.dataset.shell === 'overlay'"
        " && document.body.dataset.view === 'active-match'"
        " && document.body.classList.contains('ovx-ready')",
        timeout=15_000)
    return ctx, page, errors


def _wait_tft(page):
    page.wait_for_function(
        "() => { const h = document.getElementById('ovt-hud');"
        " return h && !h.hidden && document.body.dataset.ovxGame === 'tft'; }",
        timeout=15_000)


def _feed():
    return json.loads((FIXTURES / "tft_overlay_feed.json").read_text(encoding="utf-8"))


def _sweep(page, static_ids):
    forced = page.evaluate(_MARK, list(_FORCED))
    ex_classes = [k[6:] for k in _EXCEPTIONS if k.startswith("class:")]
    ex_ids = [k[3:] for k in _EXCEPTIONS if k.startswith("id:")]
    try:
        res = page.evaluate(_SWEEP, [static_ids + forced, ex_classes, ex_ids])
    finally:
        page.evaluate(_UNMARK)
    return res, forced


def _close(ctx, page):
    try:
        page.close()
    finally:
        ctx.close()


def test_every_hidden_overlay_element_computes_display_none(mock_server, pw_browser):
    static_ids = _static_hidden_ids()
    for must in _STATIC_OVERLAY:
        assert must in static_ids, f"{must} no longer a static hidden id"
    runs =[(f"?ui_mock=1&mode={m}&overlay=1", None, m) for m in ("sr", "aram", "arena")]
    runs.append(("?overlay=1", _feed(), "tft"))
    failures = []
    total = 0
    forced_by_mode = {}
    for query, data, label in runs:
        ctx, page, errors = _open(pw_browser, mock_server, query, data)
        try:
            if label == "tft":
                _wait_tft(page)
            else:
                page.wait_for_function(
                    "document.querySelector('#am-sub') && document.querySelector"
                    "('#am-sub').textContent.indexOf('InProgress') >= 0",
                    timeout=10_000)
            page.wait_for_timeout(500)
            res, forced = _sweep(page, static_ids)
        finally:
            _close(ctx, page)
        total += res["checked"]
        forced_by_mode[label] = len(forced)
        for b in res["bad"]:
            failures.append(f"{label} {b}")
        assert not errors, f"{label} JS errors: {errors[:3]}"
    # Anchors: the sweep saw a real page, and the TFT run reached its
    # runtime mounts (3 panels + 3 pips on each of the 12 unit slots,
    # overlay_tft.js BOARD_SLOTS), so an empty enumeration cannot pass. The
    # League runs build no TFT mount.
    assert total > 300, f"sweep checked only {total} elements"
    assert forced_by_mode["tft"] == 3 + 3 * 12, forced_by_mode
    assert forced_by_mode["sr"] == 0, forced_by_mode
    assert not failures, (
        "hidden overlay elements that still compute a display (add a [hidden] "
        "rule, or name a deliberate exception in test_hidden_display_contract."
        "_EXCEPTIONS):\n" + "\n".join(failures))


_PIPS = """
() => [...document.querySelectorAll('#ovt-board .ovt-unit')].map((u) => {
  const pips = [...u.querySelectorAll('.ovt-stars > i')];
  return {star: u.dataset.star || '', n: pips.length,
          painted: pips.filter((p) => p.getClientRects().length > 0).length,
          hidden: pips.filter((p) => p.hidden).length};
})
"""


def test_tft_star_pips_paint_only_the_star_level(mock_server, pw_browser):
    """A 1-star chip paints one pip and a 2-star chip two: the pips past the
    star level are hidden and must leave no box."""
    ctx, page, errors = _open(pw_browser, mock_server, "?overlay=1", _feed())
    try:
        _wait_tft(page)
        page.wait_for_function(
            "document.querySelectorAll('#ovt-board .ovt-unit[data-star]').length > 0"
            " && [...document.querySelectorAll('#ovt-board .ovt-unit')]"
            ".some((u) => u.dataset.star === '2')",
            timeout=10_000)
        chips = page.evaluate(_PIPS)
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"
    starred = [c for c in chips if c["star"]]
    assert {c["star"] for c in starred} >= {"1", "2"}, chips
    for c in chips:
        want = int(c["star"] or 0)
        assert c["n"] == 3, c
        assert c["hidden"] == 3 - want, c
        assert c["painted"] == want, f"hidden star pips still paint: {c}"


def test_tft_data_gated_lobby_panel_leaves_no_box(mock_server, pw_browser):
    """At the start-of-game sentinel there are no lobby rows, so w-tft-lobby
    stays hidden; a hidden overlay widget must not paint its frame."""
    data = json.loads((FIXTURES / "tft_overlay_sentinel.json").read_text(encoding="utf-8"))
    ctx, page, errors = _open(pw_browser, mock_server, "?overlay=1", data)
    try:
        _wait_tft(page)
        page.wait_for_timeout(500)
        st = page.evaluate(
            "() => { const e = document.getElementById('ovt-lobby');"
            " return e && {hidden: e.hidden, display: getComputedStyle(e).display,"
            " rects: e.getClientRects().length,"
            " widget: e.classList.contains('ovx-widget')}; }")
    finally:
        _close(ctx, page)
    assert not errors, f"JS errors: {errors[:3]}"
    assert st and st["widget"], f"lobby mount missing or not a widget: {st}"
    assert st["hidden"] is True, f"sentinel lobby panel shown: {st}"
    assert st["display"] == "none" and st["rects"] == 0, st


def test_forced_sites_are_real():
    """Each forced selector and each static overlay id still names a real
    `hidden` site (JS, or the :not([hidden]) CSS that relies on it), so the
    lists die with the code that justified them."""
    tft = (ROOT / "web" / "js" / "lib" / "overlay_tft.js").read_text(encoding="utf-8")
    ovds = (ROOT / "web" / "js" / "panels" / "overlay_ds_controls.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "css" / "overlay.css").read_text(encoding="utf-8")
    assert re.search(r'_el\(doc, "div", "ovt-panel"\);\s*el\.id = id;\s*el\.hidden = true;', tft)
    assert re.search(r"pip\.hidden = true;", tft)
    assert ".ovt-stars > i[hidden] { display: none; }" in tft
    assert re.search(r"export const BOARD_SLOTS = 12;", tft)
    assert re.search(r'getElementById\("am-pane-ovds"\)', ovds) and "pane.hidden = true;" in ovds
    for rid in ("rn-lead", "rn-choices", "rn-callouts"):
        assert f'#{rid}:not([hidden])' in css, rid
    assert _FORCED == (".ovt-panel", ".ovt-stars > i")
