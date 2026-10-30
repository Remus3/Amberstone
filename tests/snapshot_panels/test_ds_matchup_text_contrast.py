"""
tests/snapshot_panels/test_ds_matchup_text_contrast.py
RM-1142 (s144 uiux): every line of text on the Active Match DS matchup
card (#csv-sugg-ds-matchup, web/js/panels/ds_matchup.js renderDsMatchup,
styled by web/css/panels/ds_matchup.css) reaches WCAG AA on its resolved
surface, in every state the card paints and on all six themes.

MEASURED headless under /?ui_mock=1&mode=sr&theme=<t>#active-match at
1920x1080 before the fix (16-18px text at 700-800 weight, so the 4.5:1
normal-text floor applies; colours resolved by the browser and composited
over the stacked row / chip / card backgrounds, lane doc traps 3 and 4):
  pending grid row champion name, "-" verdict / swing  3.59 to 3.84:1
  pending headline "-" chip and swing-bar "-" pcts      3.70 to 3.84:1
  landed headline BACK OFF chip (--signal-bad on
  --signal-bad-soft)                                    3.70 to 4.05:1
  landed grid BACK OFF verdict (--signal-bad)           4.15 to 4.16:1
    (hextech, moonlit, arcane)
  landed grid lean-bad verdict (rgba(255, 80, 80, .9))  4.35 to 4.46:1
Everything else on the card already measured 4.77:1 or better.

The pending row also inverted its own hierarchy: the champion name (the one
thing that IS known before the fetch lands) rendered dimmer than its role
label. The champion now keeps its landed tint, the "-" sentinels sit at an
AA tint that stays dimmer than a landed swing, and the red verdicts lighten
the theme's own --signal-bad toward white (color-mix), so the hue still
follows the theme.

The card is driven through its real renderer against its real mount with
synthetic rows (hand-written champion slugs, no Riot ids), one pending pass
and one landed pass per headline verdict, the pattern
test_ds_knob_inputs_focus_ring.py uses.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VERDICTS = ["all_in", "trade", "even", "back_off"]

# Render the card in each state and return, per state, every visible element
# that owns a text node: [state, className, rowClass, text, textRGB,
# surfaceRGB]. Colours go through a 1px canvas (oklch included) and the text
# is composited over the stacked backgrounds down to the first opaque one.
_MEASURE = """async (verdicts) => {
  await document.fonts.ready;
  const cv = document.createElement('canvas'); cv.width = cv.height = 1;
  const cx = cv.getContext('2d', { willReadFrequently: true });
  const rgba = (c) => {
    cx.clearRect(0, 0, 1, 1); cx.fillStyle = '#000'; cx.fillStyle = c;
    cx.fillRect(0, 0, 1, 1);
    const d = cx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], d[3] / 255];
  };
  const over = (top, bot) => [0, 1, 2].map(
    (i) => top[i] * top[3] + bot[i] * (1 - top[3])).concat([1]);
  const surface = (el) => {
    const stack = [];
    for (let n = el; n; n = n.parentElement) {
      const b = rgba(getComputedStyle(n).backgroundColor);
      if (b[3] > 0) stack.push(b);
      if (b[3] >= 1) break;
    }
    let acc = (stack.length && stack[stack.length - 1][3] >= 1)
      ? stack.pop() : null;
    if (!acc) return null;
    while (stack.length) acc = over(stack.pop(), acc);
    return acc;
  };
  const m = await import('/js/panels/ds_matchup.js');
  const host = document.getElementById('csv-sugg-ds-matchup');
  const landed = (b, v, s) => ({ok: true, champ_a: 'Jinx', champ_b: b,
    verdict: v, swing_pct: s, pct_a_removed: 0.3, pct_b_removed: 0.55,
    notes: ['engine note'], a_can_full_combo: true});
  const row = (champ, role, lane, p) => ({champ, champA: 'Jinx', role,
    isLane: lane, payload: p});
  // One grid row per severity bin (good / lean-good / even / lean-bad / bad).
  const grid = [
    row('Kaisa', 'BOTTOM', true, landed('Kaisa', 'all_in', 70)),
    row('Teemo', 'TOP', false, landed('Teemo', 'trade', 55)),
    row('Ahri', 'MIDDLE', false, landed('Ahri', 'even', 50)),
    row('LeeSin', 'JUNGLE', false, landed('LeeSin', 'even', 35)),
    row('Thresh', 'UTILITY', false, landed('Thresh', 'back_off', 20)),
  ];
  const pending = grid.map((c) => row(c.champ, c.role, c.isLane, null));
  const read = (state) => [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map((e) => {
      const s = surface(e);
      const li = e.closest('li');
      return [state, e.className, li ? li.className : '', e.textContent,
              s ? over(rgba(getComputedStyle(e).color), s) : null, s];
    });
  const out = [];
  m._resetDsMatchup();
  m.renderDsMatchup(host, null, pending);
  out.push(...read('pending'));
  for (const v of verdicts) {
    m._resetDsMatchup();
    m.renderDsMatchup(host, landed('Kaisa', v, 50), grid);
    out.push(...read('landed-' + v));
  }
  return {hidden: host.hidden, rows: out};
}"""


def _lum(c) -> float:
    def ch(v: float) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _measure(mock_server, pw_browser, theme):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url
            + f"/?ui_mock=1&mode=sr&theme={theme}#active-match",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "(() => { const g = document.querySelector("
            "'#csv-sugg-ds-matchup .dsm-grid');"
            " return !!g && g.checkVisibility(); })()",
            timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        got = page.evaluate(_MEASURE, _VERDICTS)
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    assert not got["hidden"], "matchup card hidden"
    return got["rows"]


def _by(rows, state, cls, li=""):
    return [r for r in rows
            if r[0] == state and cls in r[1].split() and li in r[2]]


@pytest.mark.parametrize("theme", _THEMES)
def test_every_matchup_card_text_reaches_aa(mock_server, pw_browser, theme):
    rows = _measure(mock_server, pw_browser, theme)
    states = {r[0] for r in rows}
    assert states == {"pending"} | {f"landed-{v}" for v in _VERDICTS}, states
    # An empty measurement must not pass: every state paints the title, the
    # five grid rows (role / champ / verdict / swing) and the headline chip.
    for state in states:
        assert len(_by(rows, state, "dsm-grid-champ")) == 5, (state, rows)
        assert len(_by(rows, state, "dsm-grid-verdict")) == 5, state
        assert len(_by(rows, state, "dsm-verdict")) == 1, state
        if state != "pending":
            # The landed headline paints its notes, the full-combo tag too.
            assert len(_by(rows, state, "dsm-cast")) == 1, state
            assert len(_by(rows, state, "dsm-note")) == 2, state
    for state, cls, li, text, fg, bg in rows:
        assert fg is not None and bg is not None, (
            f"{theme}/{state}: {cls} {text!r} has no opaque surface"
        )
        ratio = _ratio(fg, bg)
        assert ratio >= 4.5, (
            f"{theme}/{state}: .{cls} [{li}] {text!r}"
            f" rgb{tuple(round(v) for v in fg[:3])} on"
            f" rgb{tuple(round(v) for v in bg[:3])} = {ratio:.2f}:1,"
            " below AA 4.5:1"
        )


@pytest.mark.parametrize("theme", ["hextech", "bloodmoon"])
def test_pending_row_keeps_its_hierarchy(mock_server, pw_browser, theme):
    rows = _measure(mock_server, pw_browser, theme)

    def r(row):
        return _ratio(row[4], row[5])

    for state in ("pending", "landed-even"):
        roles = _by(rows, state, "dsm-grid-role")
        champs = _by(rows, state, "dsm-grid-champ")
        assert len(roles) == len(champs) == 5, state
        for role, champ in zip(roles, champs):
            # The champion is known before its fetch lands: it never reads
            # dimmer than the role label beside it.
            assert r(champ) > r(role), (
                f"{theme}/{state}: {champ[3]!r} {r(champ):.2f}:1 not above"
                f" its role {role[3]!r} {r(role):.2f}:1"
            )
    # The "-" sentinel still reads muted next to a landed reading.
    pend = _by(rows, "pending", "dsm-grid-swing")
    land = _by(rows, "landed-even", "dsm-grid-swing")
    assert [p[3] for p in pend] == ["-"] * 5, pend
    for p, q in zip(pend, land):
        assert r(p) < r(q), (
            f"{theme}: pending swing {r(p):.2f}:1 not dimmer than landed"
            f" {q[3]!r} {r(q):.2f}:1"
        )
    # BACK OFF stays red: the lightened verdict keeps a red-dominant hue.
    for row in (_by(rows, "landed-back_off", "dsm-verdict")
                + _by(rows, "landed-even", "dsm-grid-verdict", "dsm-sev-bad")):
        red, green, blue = row[4][:3]
        assert red > green + 60 and red > blue + 60, (theme, row)
