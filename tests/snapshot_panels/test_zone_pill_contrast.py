"""
tests/snapshot_panels/test_zone_pill_contrast.py
RM-1549 (s144 uiux) - every Active Match header zone call reaches WCAG
AA (4.5:1) on its own resolved fill, in every theme.

THE DEFECT. web/css/panels/header.css painted the ENEMY ZONE call as
var(--bad) text on the 18 percent var(--bad-soft) fill over the header's
var(--canvas). The label is 16px weight 900 (RM-1548), which is not WCAG
"large" text (that needs 18.66px bold), so the 4.5:1 normal-text bar
applies. MEASURED in headless Chromium under
/?ui_mock=1&mode=sr&theme=<t>#active-match, colours resolved by the browser
(oklch included, lane doc trap 3) and the translucent fill composited over
the first opaque ancestor (the pair, not the token, trap 4):
  arcane 4.11, hextech 4.13, moonlit 4.18, bloodmoon 4.43, ember 4.49
  (under 4.5); terminal passed.
SAFE, DMZ and DEEP ENEMY measured 4.88:1 or more in every theme.

THE FIX. The ENEMY ZONE text is var(--bad) mixed 25 percent toward
var(--text) in oklab - the same red, lifted in lightness - so it clears
4.5:1 on the fill in every theme (5.72 to 6.73). --bad itself, the fill,
the pulse ring and the DEEP ENEMY solid pill are unchanged.

What is checked, per theme and per label (SAFE / DMZ / ENEMY ZONE / DEEP
ENEMY, the four classes web/js/panels/map_state.js sets):
- the text on its composited fill is at least 4.5:1;
- the ENEMY ZONE text is still red (its red channel leads green and blue
  by a clear margin) and still a different colour from var(--text), so
  the call keeps its alarm hue (HIERARCHY);
- the ENEMY ZONE fill is still the --bad-soft tint, so only the text moved,
  and DEEP ENEMY keeps its solid fill.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_THEMES = ("arcane", "hextech", "terminal", "ember", "bloodmoon", "moonlit")
_LABELS = {
    "safe": ("\u2713 SAFE", "zone-pill zone-safe"),
    "dmz": ("- DMZ", "zone-pill zone-dmz"),
    "enemy": ("\u26a0 ENEMY ZONE", "zone-pill zone-enemy"),
    "deep": ("\u26d4 DEEP ENEMY", "zone-pill zone-enemy zone-deep"),
}

# Resolve every CSS colour through a canvas (oklch and color-mix included),
# composite the translucent backgrounds from the first opaque ancestor up
# to the pill, and return the text, fill, --text and --bad-soft as sRGB.
_MEASURE_JS = """
async (labels) => {
  await document.fonts.ready;
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, base) => [0, 1, 2].map(
    (i) => top[i] * top[3] + base[i] * (1 - top[3]));
  const fill = (el) => {
    const layers = [];
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) layers.push(b);
      if (b[3] >= 1) break;
    }
    if (!layers.length || layers[layers.length - 1][3] < 1) return null;
    let acc = layers.pop().slice(0, 3);
    while (layers.length) acc = over(layers.pop(), acc);
    return acc;
  };
  const root = getComputedStyle(document.documentElement);
  const p = document.getElementById('zone-pill');
  const b = document.getElementById('zone-label');
  const out = {text: rgba(root.getPropertyValue('--text').trim()),
               badSoft: rgba(root.getPropertyValue('--bad-soft').trim()),
               rows: {}};
  for (const [key, [text, cls]] of Object.entries(labels)) {
    p.className = cls;
    b.textContent = text;
    const cs = getComputedStyle(b);
    out.rows[key] = {color: rgba(cs.color), fill: fill(b),
                     pillBg: rgba(getComputedStyle(p).backgroundColor),
                     shown: p.getClientRects().length > 0};
  }
  return out;
}
"""


def _lum(c) -> float:
    def ch(v: float) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _measure(pw_browser, mock_server, theme: str):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(viewport={"width": 1920, "height": 920})
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        page.wait_for_function(
            "() => document.body.dataset.view === 'active-match'",
            timeout=10_000)
        page.wait_for_selector("#zone-pill", state="attached", timeout=10_000)
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme
        out = page.evaluate(_MEASURE_JS, _LABELS)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{theme}]: {errors[:3]}"
    return out


@pytest.mark.parametrize("theme", _THEMES)
def test_every_zone_call_reaches_aa_on_its_fill(theme, mock_server, pw_browser):
    out = _measure(pw_browser, mock_server, theme)
    assert sorted(out["rows"]) == sorted(_LABELS), out
    for key, row in out["rows"].items():
        assert row["shown"], f"{theme}/{key}: the zone pill is not rendered"
        assert row["fill"] is not None, f"{theme}/{key}: no opaque surface"
        ratio = _ratio(row["color"], row["fill"])
        assert ratio >= 4.5, (
            f"{theme}/{key}: text rgb{tuple(row['color'][:3])} on fill"
            f" rgb{tuple(round(v) for v in row['fill'])} = {ratio:.2f}:1,"
            " below AA 4.5:1")


@pytest.mark.parametrize("theme", _THEMES)
def test_enemy_zone_keeps_its_red_call_and_its_tint(theme, mock_server, pw_browser):
    out = _measure(pw_browser, mock_server, theme)
    enemy = out["rows"]["enemy"]
    r, g, b = enemy["color"][:3]
    assert r - max(g, b) >= 60, (
        f"{theme}: ENEMY ZONE text rgb{(r, g, b)} no longer reads red")
    assert enemy["color"][:3] != out["text"][:3], (
        f"{theme}: ENEMY ZONE text is plain --text, the alarm hue is lost")
    assert enemy["pillBg"] == out["badSoft"], (
        f"{theme}: ENEMY ZONE fill {enemy['pillBg']} is not --bad-soft"
        f" {out['badSoft']}")
    deep = out["rows"]["deep"]
    assert deep["pillBg"][3] == 1, f"{theme}: DEEP ENEMY lost its solid fill"
