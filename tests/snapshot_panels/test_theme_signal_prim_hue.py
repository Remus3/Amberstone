"""
tests/snapshot_panels/test_theme_signal_prim_hue.py
RM-1319 (s144 uiux) - every derived --signal-<status> token resolves to
its own theme's semantic --<status> hue.

THE CONTRACT. web/css/tokens.css derives the status signal layer from rgb
primitive parts: --signal-good / -warn / -bad / -info / -gold are
rgb(var(--prim-green / -amber / -red / -blue / -gold)), and the -soft
members are rgba() over the same parts. web/css/themes.css states the rule
in its own header and in the ember block: a theme that re-tints a semantic
status colour (--good / --warn / --bad / --info / --gold, declared in
web/css/panels/base.css) re-tints the matching --prim-* triplet too, "so
the derived signal layer follows". Terminal, ember and bloodmoon do.

THE DEFECT. Two theme blocks re-tinted a semantic colour without its
primitive:
  - moonlit overrode --info (aqua-blue oklch(0.75 0.110 215)) and --gold
    (oklch(0.82 0.130 88)) but kept base --prim-blue / --prim-gold, so its
    --signal-info, --signal-info-soft and --signal-gold stayed hextech
    blue #7CA8FF and hextech gold #C8AA6E;
  - arcane (the default theme) overrode --gold to its lavender-silver hero
    metal (oklch(0.72 0.045 305)) but kept base --prim-gold, so every
    --signal-gold consumer (coach decision title, objective chip, player
    snapshot rail and hero numbers, team context) painted hextech gold.
coach_decisions.css paints .coach-decision-title in --signal-gold and its
selected bar in --gold, so one card showed two different "golds".

THE FIX. The moonlit block declares --prim-blue and --prim-gold, the arcane
block --prim-gold, each the rgb parts of that block's own hex line.

WHAT IS MEASURED (headless Chromium, computed values, never a grep): for
the base hextech palette and EVERY :root[data-theme] block, each pair
(--signal-X, --X) is resolved through color-mix(in srgb, ...), so an
oklch() semantic declaration is compared as the sRGB the browser paints.
The pair must agree within 3/255 per channel (each hex fallback is the
sRGB-clamped equivalent of its oklch line). --signal-info-soft must carry
--info's hue at 0.18 alpha.
"""
import re
from pathlib import Path

from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent

# (signal token, semantic token) - the status pairs tokens.css derives from
# a --prim-* triplet that base.css also states as a semantic colour.
PAIRS = (
    ("signal-good", "good"),
    ("signal-warn", "warn"),
    ("signal-bad", "bad"),
    ("signal-info", "info"),
    ("signal-gold", "gold"),
)
TOL = 3          # per channel, 0-255
ALPHA = 0.18

_RESOLVE_JS = r"""
(names) => {
  const d = document.createElement('div');
  document.body.appendChild(d);
  const read = (v) => {
    d.style.color = 'color-mix(in srgb, var(' + v + ') 100%, transparent 0%)';
    return getComputedStyle(d).color;
  };
  const out = {};
  for (const n of names) { out[n] = read('--' + n); }
  d.remove();
  return out;
}
"""

_NUM = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")


def _parse(col):
    """Parse a computed colour into (r, g, b, a) on 0-255 / 0-1 scales."""
    nums = [float(x) for x in _NUM.findall(col)]
    if col.startswith("color(srgb"):
        r, g, b = (round(v * 255, 2) for v in nums[:3])
        a = nums[3] if len(nums) > 3 else 1.0
    elif col.startswith("rgb"):
        r, g, b = nums[:3]
        a = nums[3] if len(nums) > 3 else 1.0
    else:
        raise AssertionError(f"unexpected computed colour form: {col!r}")
    return r, g, b, a


def _themes():
    text = (ROOT / "web" / "css" / "themes.css").read_text(encoding="utf-8")
    return sorted(set(re.findall(r':root\[data-theme="([a-z0-9_-]+)"\]', text)))


def _names():
    names = []
    for sig, sem in PAIRS:
        names += [sig, sem]
    return names + ["signal-info-soft"]


def _measure_all(pw_browser, mock_server):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 920}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    got = {}
    try:
        page.goto(
            mock_server.url + "/?ui_mock=1#home",
            wait_until="domcontentloaded",
            timeout=15_000,
        )
        page.wait_for_function(
            "document.body.dataset.view === 'home'", timeout=10_000
        )
        for t in ["hextech"] + _themes():
            if t == "hextech":
                page.evaluate(
                    "() => document.documentElement.removeAttribute('data-theme')"
                )
            else:
                page.evaluate(
                    "(t) => document.documentElement.setAttribute('data-theme', t)",
                    t,
                )
            got[t] = page.evaluate(_RESOLVE_JS, _names())
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors: {errors[:3]}"
    return got


def _delta(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _failures(got):
    bad = []
    for theme, vals in got.items():
        for sig, sem in PAIRS:
            s, m = _parse(vals[sig]), _parse(vals[sem])
            if _delta(s, m) > TOL:
                bad.append((theme, sig, vals[sig], sem, vals[sem]))
        soft, info = _parse(vals["signal-info-soft"]), _parse(vals["info"])
        if _delta(soft, info) > TOL or abs(soft[3] - ALPHA) > 0.01:
            bad.append((theme, "signal-info-soft", vals["signal-info-soft"],
                        "info", vals["info"]))
    return bad


def test_every_signal_token_matches_its_themes_semantic_hue(
    mock_server, pw_browser
):
    got = _measure_all(pw_browser, mock_server)
    assert len(got) >= 6, f"theme scan anchor: {sorted(got)}"
    fails = _failures(got)
    assert not fails, f"signal / semantic hue mismatches: {fails[:8]}"


def test_named_pairs_moonlit_info_and_arcane_moonlit_gold(
    mock_server, pw_browser
):
    # The specific RM-1319 pairs, so a regression names itself.
    got = _measure_all(pw_browser, mock_server)
    for theme, sig, sem in (
        ("moonlit", "signal-info", "info"),
        ("moonlit", "signal-gold", "gold"),
        ("arcane", "signal-gold", "gold"),
    ):
        s, m = _parse(got[theme][sig]), _parse(got[theme][sem])
        assert _delta(s, m) <= TOL, (theme, sig, got[theme][sig],
                                     sem, got[theme][sem])
    # Arcane's hero metal is lavender-silver (blue >= red), never gold.
    r, g, b, _ = _parse(got["arcane"]["signal-gold"])
    assert b >= r, f"arcane --signal-gold still gold: {got['arcane']}"


def test_theme_flip_is_not_inert(mock_server, pw_browser):
    # Anchor: an inert theme flip would make the pair check trivially pass.
    got = _measure_all(pw_browser, mock_server)
    golds = {got[t]["signal-gold"] for t in got}
    goods = {got[t]["signal-good"] for t in got}
    assert len(golds) >= 3, f"--signal-gold identical across themes: {golds}"
    assert len(goods) >= 3, f"--signal-good identical across themes: {goods}"
