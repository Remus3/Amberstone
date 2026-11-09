"""
tests/snapshot_panels/test_lobby_text_contrast.py
S144-U-202 (s144 uiux): every text line on the Pre-Game Lobby view reaches
its WCAG contrast floor on its resolved surface, in every theme, at the
1920x1080 baseline and the 923x1280 companion window, and both two-state
queue toggles (Accept On / Off, Party Open / Closed) reach AA in BOTH of
their states.

Drive path: /?ui_mock=1#lobby, the recipe and landing signal of
test_lobby_view.py (#lv-queue-name leaves its "-" placeholder, and the
party roster mounts a .lobby-member-row).

Colours are resolved by the browser and composited over the stacked
backgrounds (lane doc traps 3 and 4): the pair is fg on its own surface.
A text line inside a disabled control (opacity hold, WCAG 1.4.3 exempts
inactive components) is skipped by the whole-view sweep.

The toggles are measured on the one real button each: the test re-stamps
the state class and the line-2 text exactly as main.js _syncAutoAcceptUI /
the party-toggle renderer do (classList is-on / is-off, is-open /
is-closed), then reads the computed colour.
"""
import pytest

from tests.snapshot_panels.conftest import _WS_STUB
from tests.snapshot_panels.test_ds_cards_muted_text_contrast import _HELPERS
from tests.snapshot_panels.test_ds_matchup_text_contrast import _ratio

_THEMES = ["hextech", "terminal", "ember", "bloodmoon", "moonlit", "arcane"]
_VIEWPORTS = [(1920, 1080), (923, 1280)]
_IDS = [f"{w}x{h}" for w, h in _VIEWPORTS]
_AA = 4.5
_AA_LARGE = 3.0

_TOGGLES = {
    "lv-auto-accept": (("is-on", "On"), ("is-off", "Off")),
    "lv-party-toggle": (("is-open", "Open"), ("is-closed", "Closed")),
}

_MEASURE = """async (toggles) => {
  await document.fonts.ready;
""" + _HELPERS + """
  const host = document.getElementById('view-lobby');
  const row = (e) => {
    const s = surface(e);
    const cs = getComputedStyle(e);
    return {
      cls: String(e.className), id: e.id,
      text: e.textContent.trim().slice(0, 40),
      fg: s ? over(rgba(cs.color), s) : null, bg: s,
      size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10),
      inactive: !!e.closest(
        ':disabled, [aria-disabled="true"], .is-disabled'),
    };
  };
  const all = [...host.querySelectorAll('*')]
    .filter((e) => [...e.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim()))
    .filter((e) => e.checkVisibility())
    .map(row);
  const empties = [...host.querySelectorAll('.lv-party-empty')]
    .filter((e) => e.checkVisibility()).map(row);
  const names = [...host.querySelectorAll('.lobby-member-name')]
    .filter((e) => e.checkVisibility()).map(row);
  const states = {};
  for (const [id, pairs] of Object.entries(toggles)) {
    const btn = document.getElementById(id);
    const line = btn.querySelector('.lq-btn-line2');
    const label = btn.querySelector('.lq-btn-line1');
    const keep = [btn.className, line.textContent];
    const all_cls = pairs.map((p) => p[0]);
    states[id] = {label: row(label)};
    for (const [cls, text] of pairs) {
      btn.classList.remove(...all_cls);
      btn.classList.add(cls);
      line.textContent = text;
      states[id][cls] = row(line);
    }
    btn.className = keep[0];
    line.textContent = keep[1];
  }
  const root = getComputedStyle(document.documentElement);
  const tok = (n) => rgba(root.getPropertyValue(n).trim());
  return {all, empties, names, states,
          text: tok('--text'), dim: tok('--text-dim')};
}"""


def _measure(mock_server, pw_browser, theme, vp):
    mock_server._store["data"] = {}
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": vp[0], "height": vp[1]}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    try:
        page.goto(
            mock_server.url + f"/?ui_mock=1&theme={theme}#lobby",
            wait_until="domcontentloaded", timeout=15_000,
        )
        page.wait_for_function(
            "() => { const q = document.getElementById('lv-queue-name');"
            " return q && q.textContent.trim() && q.textContent.trim() !== '-'"
            " && document.querySelector('#lv-members-list .lobby-member-row'); }",
            timeout=10_000,
        )
        assert page.evaluate(
            "document.documentElement.dataset.theme || 'hextech'"
        ) == theme, f"booted on the wrong theme, not {theme}"
        got = page.evaluate(_MEASURE, {k: list(v) for k, v in _TOGGLES.items()})
    finally:
        page.close()
        ctx.close()
    assert not errors, errors[:3]
    return got


@pytest.fixture(scope="module")
def measured():
    return {}


def _get(measured, mock_server, pw_browser, theme, vp):
    key = (theme, vp)
    if key not in measured:
        measured[key] = _measure(mock_server, pw_browser, theme, vp)
    return measured[key]


def _large(row):
    return row["size"] >= 24 or (row["size"] >= 18.66 and row["weight"] >= 700)


@pytest.mark.parametrize("theme", _THEMES)
def test_both_toggle_states_reach_aa(theme, measured, mock_server,
                                     pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    low = {}
    for btn, pairs in _TOGGLES.items():
        for cls, text in pairs:
            row = got["states"][btn][cls]
            assert row["text"] == text.upper() or row["text"] == text, row
            assert row["bg"] is not None, (btn, cls, theme)
            # 16 px / 700: not WCAG large text, so 4.5 applies.
            assert not _large(row), (btn, cls, row)
            ratio = _ratio(row["fg"], row["bg"])
            if ratio < _AA:
                low[f"{btn}.{cls}"] = round(ratio, 2)
    assert not low, f"under AA {_AA} on {theme}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_the_off_and_closed_states_stay_red(theme, measured, mock_server,
                                            pw_browser):
    """The lift mixes toward --text; Off / Closed must stay a red and On /
    Open a green, so the state still reads by hue as well as by word."""
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    for btn, (good, bad) in (("lv-auto-accept", ("is-on", "is-off")),
                             ("lv-party-toggle", ("is-open", "is-closed"))):
        r, g, b = got["states"][btn][bad]["fg"][:3]
        assert r - max(g, b) >= 60, (btn, bad, theme, (r, g, b))
        r, g, b = got["states"][btn][good]["fg"][:3]
        assert g - max(r, b) >= 20, (btn, good, theme, (r, g, b))


@pytest.mark.parametrize("vp", _VIEWPORTS, ids=_IDS)
@pytest.mark.parametrize("theme", _THEMES)
def test_every_lobby_text_line_reaches_its_floor(theme, vp, measured,
                                                 mock_server, pw_browser):
    got = _get(measured, mock_server, pw_browser, theme, vp)
    rows = [r for r in got["all"] if not r["inactive"]]
    assert len(rows) >= 20, f"Lobby rendered too little text: {got['all']}"
    assert got["empties"], f"no visible .lv-party-empty on {theme} at {vp}"
    low = []
    for row in rows:
        assert row["bg"] is not None, (theme, vp, row)
        floor = _AA_LARGE if _large(row) else _AA
        ratio = _ratio(row["fg"], row["bg"])
        if ratio < floor:
            low.append((row["cls"], row["id"], row["text"], round(ratio, 2),
                        floor))
    assert not low, f"under the WCAG floor on {theme} at {vp}: {low}"


@pytest.mark.parametrize("theme", _THEMES)
def test_the_empty_marks_stay_secondary(theme, measured, mock_server,
                                        pw_browser):
    """The lift must not invert the hierarchy. The member names are party
    IDENTITY colours (data-color-idx -> --info / --good / --gold / ...), so
    their luminance is not the yardstick. Instead: a party row's "-" /
    unranked mark paints the secondary token --text-dim, sits under the
    primary --text on its own surface, and stays lighter-weight than the
    800-weight member name beside it."""
    got = _get(measured, mock_server, pw_browser, theme, _VIEWPORTS[0])
    assert got["names"] and got["empties"], got
    name_weight = min(n["weight"] for n in got["names"])
    for row in got["empties"]:
        assert row["fg"][:3] == got["dim"][:3], (theme, row, got["dim"])
        primary = _ratio(over_opaque(got["text"], row["bg"]), row["bg"])
        assert _ratio(row["fg"], row["bg"]) < primary, (theme, row)
        assert row["weight"] < name_weight, (theme, row, name_weight)


def over_opaque(top, bot):
    """Composite a token colour over the row's opaque surface."""
    a = top[3]
    return [top[i] * a + bot[i] * (1 - a) for i in range(3)] + [1]
