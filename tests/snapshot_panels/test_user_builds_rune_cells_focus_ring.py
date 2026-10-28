"""
tests/snapshot_panels/test_user_builds_rune_cells_focus_ring.py
RM-1087 (s144 uiux): the User Builds rune page builder's rune cells
(.ub-rp-rune buttons, main.js _ubRpBuildRow) are keyboard-pickable, and
focus is carried across the rebuild since RM-1085, but measured in
headless Chromium under /?ui_mock=1#user-builds a focused cell drew only
the UA outline, not the one system focus ring (tokens.css --focus-ring)
that the tree tabs draw since RM-1084.

Fix: .ub-rp-rune:focus-visible draws var(--focus-ring) with outline none
(web/css/panels/header.css, next to the tree tab rule).

Probe: every cell of every kind - keystone row, primary minors, secondary
minors - focused under keyboard modality (a Shift press first, so a
programmatic focus() matches :focus-visible as a Tab would), in every
theme. The ring is RESOLVED off a probe element styled with
var(--focus-ring), not grepped. A SELECTED cell (keystone picked) must
draw the ring too, and a cell with no focus must draw no shadow, so the
ring is not just painted on every cell.

Drive path shared with test_user_builds_rune_tabs.py (its _open): Tristana,
+ Add build, the TRACKED DDragon rune dump served for /api/dictionary/runes,
primary Precision, secondary Sorcery, transitions off.
"""
import pytest

from tests.snapshot_panels.test_tab_bars_selected_state import _THEMES
from tests.snapshot_panels.test_user_builds_rune_tabs import _open

_CELLS = "#ub-rp-primary-rows .ub-rp-rune, #ub-rp-secondary-rows .ub-rp-rune"

_PROBE = """
([sel, themes]) => {
  const root = document.documentElement;
  const out = {};
  for (const t of themes) {
    if (t === 'hextech') root.removeAttribute('data-theme');
    else root.dataset.theme = t;
    const probe = document.createElement('div');
    probe.style.boxShadow = 'var(--focus-ring)';
    document.body.appendChild(probe);
    const ring = getComputedStyle(probe).boxShadow;
    probe.remove();
    out[t] = {
      ring,
      cells: Array.from(document.querySelectorAll(sel)).map((el) => {
        el.focus();
        const cs = getComputedStyle(el);
        const row = {
          rune: el.dataset.rune,
          kind: el.classList.contains('ub-rp-rune-keystone') ? 'keystone'
            : (el.closest('#ub-rp-secondary-rows') ? 'secondary' : 'primary'),
          selected: el.classList.contains('selected'),
          focused: el === document.activeElement,
          visible: el.matches(':focus-visible'),
          outline: cs.outlineStyle,
          shadow: cs.boxShadow,
        };
        el.blur();
        row.idleShadow = getComputedStyle(el).boxShadow;
        return row;
      }),
    };
  }
  root.removeAttribute('data-theme');
  return out;
}
"""


@pytest.fixture(scope="module")
def probed(mock_server, pw_browser):
    ctx, page, errors = _open(pw_browser, mock_server)
    try:
        # Pick the first keystone so one probed cell is focused AND selected.
        page.click("#ub-rp-primary-rows .ub-rp-rune-keystone")
        page.wait_for_selector(
            "#ub-rp-primary-rows .ub-rp-rune-keystone.selected", timeout=5_000,
        )
        page.keyboard.press("Shift")
        data = page.evaluate(_PROBE, [_CELLS, _THEMES])
    finally:
        page.close()
        ctx.close()
    return {"data": data, "errors": errors}


def test_rendered_without_errors(probed):
    assert not probed["errors"], probed["errors"][:3]


def test_every_cell_kind_was_probed(probed):
    for theme, d in probed["data"].items():
        kinds = {c["kind"] for c in d["cells"]}
        assert kinds == {"keystone", "primary", "secondary"}, (theme, kinds)
        assert any(c["selected"] and c["kind"] == "keystone" for c in d["cells"]), theme


@pytest.mark.parametrize("theme", _THEMES)
def test_focused_rune_cell_draws_the_system_focus_ring(probed, theme):
    d = probed["data"][theme]
    ring = d["ring"]
    assert ring not in ("", "none"), f"{theme}: --focus-ring resolved {ring!r}"
    for c in d["cells"]:
        tag = f"{theme}: {c['kind']} {c['rune']}"
        assert c["focused"] and c["visible"], f"{tag}: not :focus-visible"
        assert c["outline"] == "none", f"{tag}: outline {c['outline']!r}"
        assert c["shadow"] == ring, f"{tag}: shadow {c['shadow']!r} != ring {ring!r}"


@pytest.mark.parametrize("theme", _THEMES)
def test_unfocused_rune_cell_draws_no_ring(probed, theme):
    for c in probed["data"][theme]["cells"]:
        assert c["idleShadow"] == "none", (
            f"{theme}: {c['kind']} {c['rune']} idle shadow {c['idleShadow']!r}"
        )
