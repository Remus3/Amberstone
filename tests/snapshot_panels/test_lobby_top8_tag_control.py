"""
tests/snapshot_panels/test_lobby_top8_tag_control.py
The Pre-Game Lobby "My Top 8" rows: the only click target a row carries is
a real, keyboard-reachable, --hit-min control (session 144, lane uiux,
RM-980).

MEASURED in headless Chromium over the 3-entry /api/top8 seed (the
test_lobby_hit_targets.py harness, 1920x1080 viewport; 1920x920 and
923x1280 re-measured the same):
- web/css/panels/header.css set `.lv-top8-row { cursor: pointer; }`, but
  no handler is bound to the row: _wireTop8Actions (web/js/main.js) wires
  only `[data-action]` descendants. Pointing anywhere on the name, games,
  role or rank cells showed a hand and clicking did nothing - a false
  affordance on most of every row.
- The one row-level control, the tag cell (`data-action="edit-tag"`, the
  "+ tag" / user-tag text), was a <span> with a click listener: tabIndex
  -1, so a keyboard user could never reach it, and its effective hit
  target (elementFromPoint walk) was 20px tall, under the 42px --hit-min
  floor.

Rule pinned here, by COMPUTED value and real hit testing:
- no filled row shows a pointer cursor over a cell that does nothing;
- the edit-tag control is focusable, draws a solid >= 2px --accent ring
  under :focus-visible, and Enter on it opens the tag prompt;
- its effective hit target (elementFromPoint walked out from its own
  centre) is at least the resolved --hit-min tall, and it still owns its
  own centre (the RM-338 sweep in test_lobby_hit_targets.py covers the
  neighbours);
- the rows do not grow and the page gains no horizontal overflow.
"""
from tests.snapshot_panels.test_lobby_hit_targets import (
    _EFFECTIVE_EXTENT_JS,
    _open_top8,
)

_TAG = '#lv-top8-list .lv-top8-tag[data-action="edit-tag"][data-idx="1"]'

_TOKENS_JS = r"""
() => {
  const probe = (prop, v) => {
    const d = document.createElement("span");
    d.style.display = "block";
    d.style[prop] = "var(" + v + ")";
    document.body.appendChild(d);
    const cs = getComputedStyle(d);
    const out = prop === "color" ? cs.color : parseFloat(cs[prop]);
    d.remove();
    return out;
  };
  return {hitMin: probe("height", "--hit-min"),
          accent: probe("color", "--accent")};
}
"""


def test_top8_row_cells_do_not_advertise_a_click(mock_server, pw_browser):
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    try:
        rows = page.evaluate(r"""
        () => Array.from(document.querySelectorAll(
          '#lv-top8-list .lv-top8-row:not(.is-placeholder)')).map((row) => ({
            row: getComputedStyle(row).cursor,
            cells: Array.from(row.querySelectorAll(
              '.lv-top8-name, .lv-top8-games, .lv-top8-role, .lv-top8-rank'))
              .map((c) => getComputedStyle(c).cursor),
        }))
        """)
        assert len(rows) == 3, rows
        lying = [r for r in rows
                 if r["row"] == "pointer" or "pointer" in r["cells"]]
        assert lying == [], (
            "a Top 8 row shows a pointer over cells no handler serves: "
            + str(rows)
        )
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 row cursor]: {errors[:3]}"


def test_top8_tag_control_is_keyboard_reachable(mock_server, pw_browser):
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    dialogs: list[str] = []

    def _on_dialog(d):
        dialogs.append(d.type + ":" + d.message)
        d.dismiss()

    page.on("dialog", _on_dialog)
    try:
        tok = page.evaluate(_TOKENS_JS)
        r = page.evaluate(r"""
        (sel) => {
          const el = document.querySelector(sel);
          if (!el) return null;
          el.focus();
          const cs = getComputedStyle(el);
          return {
            tag: el.tagName,
            tabIndex: el.tabIndex,
            focused: document.activeElement === el,
            focusVisible: el.matches(":focus-visible"),
            outlineStyle: cs.outlineStyle,
            outlineWidth: parseFloat(cs.outlineWidth),
            outlineColor: cs.outlineColor,
            text: el.textContent.trim(),
          };
        }
        """, _TAG)
        assert r is not None, "edit-tag control for idx 1 did not render"
        assert r["tabIndex"] >= 0 and r["focused"], r
        assert r["focusVisible"], r
        assert r["outlineStyle"] == "solid", r
        assert r["outlineWidth"] >= 2, r
        assert r["outlineColor"] == tok["accent"], (r, tok)
        assert r["text"] == "+ tag", r
        page.keyboard.press("Enter")
        page.wait_for_timeout(200)
        assert any(d.startswith("prompt:User tag for Bravo#BBB")
                   for d in dialogs), dialogs
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 tag keyboard]: {errors[:3]}"


def test_top8_tag_control_is_a_hit_min_target(mock_server, pw_browser):
    ctx, page, errors = _open_top8(mock_server, pw_browser)
    try:
        tok = page.evaluate(_TOKENS_JS)
        assert tok["hitMin"] >= 42, tok
        ext = page.evaluate(_EFFECTIVE_EXTENT_JS, _TAG)
        assert ext and ext.get("ownsCentre"), ext
        assert ext["height"] >= tok["hitMin"], (ext, tok)
        geo = page.evaluate(r"""
        () => ({
          rows: Array.from(document.querySelectorAll(
            '#lv-top8-list .lv-top8-row')).map(
              (r) => Math.round(r.getBoundingClientRect().height)),
          overflowX: document.documentElement.scrollWidth > innerWidth,
        })
        """)
        assert max(geo["rows"]) <= 39, geo
        assert geo["overflowX"] is False, geo
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [top8 tag hit target]: {errors[:3]}"
