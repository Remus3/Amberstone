"""
tests/snapshot_panels/test_overlay_build_threats_clip.py
S144-U-282 (s144 uiux): in the overlay shell the BUILD widget (w-build)
shows its whole THREATS strip - the "THREATS" eyebrow and every enemy
portrait + damage-mix donut - inside its own clip at the real overlay
height, in every League mode, without growing into another widget.

THE DEFECT. QA ledger FUTURE (h) of S144-U-280. The overlay field is
1920x1080 design px (rc-shell sizes the window by ovscale, so a 2560x1440
screen is H 1080 too). overlay_layout._applyPos bottom-anchors a TALL
widget only when its stored y is in the lower half (y > H * 0.5). The
w-build default was (70, 470): at H 920 that is the lower half, so the
widget sat on the bottom-left corner and grew upward to fit; at H 1080 it
is the UPPER half (470 < 540), so the widget was top-anchored with
--ovx-maxh 594 and the .am-pane overflow: hidden clip at y 1064. Measured
headless (mock server, ?ui_mock=1&mode=<m>&overlay=1, 1920x1080):
  - sr: the capability-gap chip (489 - 602) and the rerank module
    (624 - 1046) left the "THREATS" eyebrow at 1056 - 1079, sliced through
    by the clip, and the strip (1089 - 1163) wholly below it;
  - arena: the 10-enemy strip ran 969 - 1085, three rows, the last one
    under the clip.
The same strip fit at H 920, so the real overlay height was the one place
it clipped.

THE FIX (web/js/lib/overlay_layout.js WIDGETS). The w-build default y
moves into the lower half (470 -> 600), so the widget takes the
bottom-anchored path at every height below 1200: bottom 16 px, growing
upward with its content. tests/test_overlay_default_layout_collision.py
models that path and keeps the grown box clear of w-call.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_MODES = ["sr", "aram", "mayhem", "arena", "brawl"]
_HEIGHTS = [1080, 920]
_W = '.ovx-widget[data-ovx-id="w-build"]'
_SHEET = "*, *::before, *::after { transition: none !important; }"

# One synchronous read: the widget clip, the THREATS eyebrow and strip,
# every child of #am-build-body, and the box of every other visible widget.
_READ = """(wsel) => {
  const box = (r) => ({left: r.left, right: r.right, top: r.top,
                       bottom: r.bottom});
  const w = document.querySelector(wsel);
  if (!w) return null;
  const wr = w.getBoundingClientRect();
  const clip = {left: wr.left + w.clientLeft, top: wr.top + w.clientTop};
  clip.right = clip.left + w.clientWidth;
  clip.bottom = clip.top + w.clientHeight;
  const body = w.querySelector('#am-build-body');
  const kids = body ? [...body.children].map((k) => ({
    cls: k.className, text: (k.textContent || '').trim().slice(0, 24),
    box: box(k.getBoundingClientRect())})) : [];
  let eyebrow = null;
  for (const k of (body ? body.children : [])) {
    if ((k.textContent || '').trim().startsWith('THREATS')) {
      eyebrow = box(k.getBoundingClientRect());
      break;
    }
  }
  const strip = w.querySelector('.threat-strip');
  const others = [];
  for (const o of document.querySelectorAll('.ovx-widget')) {
    if (o === w || !o.checkVisibility()) continue;
    const r = o.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    others.push({id: o.dataset.ovxId, box: box(r)});
  }
  return {clip: clip, wbox: box(wr), vh: window.innerHeight,
          kids: kids, eyebrow: eyebrow,
          strip: strip ? box(strip.getBoundingClientRect()) : null,
          enemies: strip ? strip.querySelectorAll('.threat-row').length : 0,
          others: others};
}"""


@pytest.fixture(scope="module")
def measured():
    return {}


def _measure(mock_server, pw_browser, mode, height):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": height})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(mock_server.url + f"/?ui_mock=1&mode={mode}&overlay=1",
                  wait_until="domcontentloaded", timeout=15_000)
        page.wait_for_function(
            "() => document.body.dataset.shell === 'overlay'"
            " && document.body.classList.contains('ovx-ready')",
            timeout=10_000)
        # The THREATS strip is the build body's last paint.
        page.wait_for_selector(f"{_W} .threat-strip .threat-row",
                               state="attached", timeout=10_000)
        page.add_style_tag(content=_SHEET)
        # Let the layout pass re-place the widget against its grown content.
        page.wait_for_timeout(300)
        got = page.evaluate(_READ, _W)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert got, "w-build is not on the page"
    return got


def _get(measured, mock_server, pw_browser, mode, height):
    key = (mode, height)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, mode, height)
    return measured[key]


def _inside(clip, b):
    return (b["left"] >= clip["left"] - 0.5
            and b["right"] <= clip["right"] + 0.5
            and b["top"] >= clip["top"] - 0.5
            and b["bottom"] <= clip["bottom"] + 0.5)


@pytest.mark.parametrize("height", _HEIGHTS)
@pytest.mark.parametrize("mode", _MODES)
def test_the_threats_strip_sits_inside_the_widget_clip(
        mode, height, measured, mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, mode, height)
    clip = got["clip"]
    # A real clip: the widget's own box, not a zero or unbounded one.
    assert 300 < clip["bottom"] - clip["top"] <= height, clip
    # The strip is on the page with its roster, so an empty read cannot
    # pass: 5 enemies on a 5v5 map, the other 10 teams' players in Arena.
    assert got["eyebrow"], f"{mode} {height}: no THREATS eyebrow"
    assert got["strip"], f"{mode} {height}: no .threat-strip"
    assert got["enemies"] == (10 if mode == "arena" else 5), got["enemies"]
    bad = []
    for name in ("eyebrow", "strip"):
        b = got[name]
        if not _inside(clip, b):
            bad.append(f"{name} top {b['top']:.0f} bottom {b['bottom']:.0f}")
    assert not bad, (
        f"{mode} {height}: outside the w-build clip (top {clip['top']:.0f},"
        f" bottom {clip['bottom']:.0f}): " + "; ".join(bad))


@pytest.mark.parametrize("height", _HEIGHTS)
@pytest.mark.parametrize("mode", _MODES)
def test_no_build_body_row_is_cut_by_the_clip(
        mode, height, measured, mock_server, pw_browser):
    # Every row of #am-build-body (the rerank module, each eyebrow, each
    # strip) paints whole: none is sliced or hidden by the widget edge.
    got = _get(measured, mock_server, pw_browser, mode, height)
    assert len(got["kids"]) >= 3, got["kids"]
    cut = [f"{k['cls'] or k['text']!r} {k['box']['top']:.0f}-"
           f"{k['box']['bottom']:.0f}"
           for k in got["kids"] if not _inside(got["clip"], k["box"])]
    assert not cut, (f"{mode} {height}: cut at clip bottom"
                     f" {got['clip']['bottom']:.0f}: " + "; ".join(cut))


@pytest.mark.parametrize("height", _HEIGHTS)
@pytest.mark.parametrize("mode", _MODES)
def test_the_widget_sits_on_the_bottom_left_corner(
        mode, height, measured, mock_server, pw_browser):
    # The bottom-anchored path: bottom edge 16 px above the field's bottom,
    # left edge at the registry x (70).
    got = _get(measured, mock_server, pw_browser, mode, height)
    wb = got["wbox"]
    assert abs(wb["bottom"] - (got["vh"] - 16)) <= 1.0, (mode, height, wb)
    assert abs(wb["left"] - 70) <= 1.0, (mode, height, wb)


@pytest.mark.parametrize("mode", _MODES)
def test_the_grown_widget_overlaps_no_other_visible_widget(
        mode, measured, mock_server, pw_browser):
    # Growing upward must not run the box into another widget at the real
    # overlay height (w-call sits above it on the same left edge).
    got = _get(measured, mock_server, pw_browser, mode, 1080)
    wb = got["wbox"]
    assert got["others"], f"{mode}: no other widget visible to check against"
    assert any(o["id"] == "w-call" for o in got["others"]), (
        f"{mode}: w-call not visible: {[o['id'] for o in got['others']]}")
    hits = []
    for o in got["others"]:
        b = o["box"]
        x = min(wb["right"], b["right"]) - max(wb["left"], b["left"])
        y = min(wb["bottom"], b["bottom"]) - max(wb["top"], b["top"])
        if x > 0.5 and y > 0.5:
            hits.append(f"{o['id']} ({x:.0f} x {y:.0f} px)")
    assert not hits, f"{mode}: w-build overlaps " + ", ".join(hits)
