"""
tests/snapshot_panels/test_user_builds_row_actions_hit.py
RM-1007 (s144 uiux): the per-row Edit / Delete buttons on the User Builds
page meet the --hit-min fingertip floor and show the accent focus ring.

Before this slice `.ub-btn-tiny` (web/css/panels/header.css) set
`min-height: 0` with the comment "row-scoped; floor relaxed", which carried
no operator-exception wording, so the row actions rendered 28px tall - the
only User Builds clickables under the 42px floor (the toolbar "+ Add build"
and the form Save / Cancel / close already inherit `.ub-btn`'s
`min-height: var(--hit-min)`). No `.ub-btn` rule declared a `:focus-visible`
style either, unlike its header.css siblings (`.history-filter-rbtn`,
`.lv-top8-tag`, `.set-action-btn`).

Every value is read COMPUTED in real headless Chromium (lane doc section 6:
a grep-based token audit passes an undefined var). --hit-min and --accent
are resolved through the live cascade, never hard-coded here.

Drive path: /?ui_mock=1#user-builds -> _userBuildsFetchAndRender loads
/data/ui_mock/user_builds.json. Landing signal: a .ub-build-row appears.
"""
import pytest

from tests.snapshot_panels.test_user_builds_review_r30 import _open_user_builds

# 1920x920 = the design baseline viewport with Chrome chrome (CLAUDE.md);
# 923x1280 = the companion width the lobby / reflow tests also use.
VIEWPORTS = [(1920, 920), (923, 1280)]

_MEASURE = """
() => {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;visibility:hidden;'
    + 'height:var(--hit-min);font-size:var(--fs-xs);color:var(--accent)';
  document.body.appendChild(probe);
  const cs = getComputedStyle(probe);
  const tokens = {
    hit: parseFloat(cs.height),
    fsXs: parseFloat(cs.fontSize),
    accent: cs.color,
  };
  probe.remove();
  const btns = Array.from(
    document.querySelectorAll('#view-user-builds .ub-build-row .ub-btn-tiny'));
  const rows = btns.map(b => {
    const r = b.getBoundingClientRect();
    const row = b.closest('.ub-build-row').getBoundingClientRect();
    return {
      text: b.textContent.trim(),
      tag: b.tagName,
      w: r.width, h: r.height,
      fs: parseFloat(getComputedStyle(b).fontSize),
      inRow: r.top >= row.top - 0.5 && r.bottom <= row.bottom + 0.5
        && r.left >= row.left - 0.5 && r.right <= row.right + 0.5,
    };
  });
  return {tokens, rows};
}
"""


@pytest.mark.parametrize("width,height", VIEWPORTS)
def test_ub_row_actions_meet_hit_min(mock_server, pw_browser, width, height):
    ctx, page, errors = _open_user_builds(pw_browser, mock_server, width, height)
    try:
        m = page.evaluate(_MEASURE)
    finally:
        page.close()
        ctx.close()
    tok = m["tokens"]
    assert tok["hit"] >= 42, f"--hit-min resolved to {tok['hit']}px"
    assert tok["fsXs"] >= 16, f"--fs-xs resolved to {tok['fsXs']}px"
    rows = m["rows"]
    # the Tristana mock carries several builds -> an Edit + Delete per row.
    texts = [r["text"] for r in rows]
    assert texts.count("Edit") >= 2 and texts.count("Delete") >= 2, texts
    for r in rows:
        assert r["tag"] == "BUTTON", r
        assert r["h"] >= tok["hit"] - 0.5, f"{r['text']} {r['h']}px tall < --hit-min"
        assert r["w"] >= tok["hit"] - 0.5, f"{r['text']} {r['w']}px wide < --hit-min"
        assert r["fs"] >= tok["fsXs"], f"{r['text']} font {r['fs']}px < --fs-xs"
        assert r["inRow"], f"{r['text']} spills out of its .ub-build-row"
    assert not errors, f"JS errors: {errors[:3]}"


_FOCUS = """
() => {
  const probe = document.createElement('div');
  probe.style.cssText = 'position:absolute;visibility:hidden;color:var(--accent)';
  document.body.appendChild(probe);
  const accent = getComputedStyle(probe).color;
  probe.remove();
  const out = [];
  const sel = ['#view-user-builds .ub-build-row .ub-btn-ghost.ub-btn-tiny',
               '#view-user-builds .ub-build-row .ub-btn-danger.ub-btn-tiny',
               '#ub-add-btn'];
  for (const s of sel) {
    const b = document.querySelector(s);
    if (!b) { out.push({sel: s, missing: true}); continue; }
    b.focus();
    const cs = getComputedStyle(b);
    out.push({
      sel: s,
      focused: document.activeElement === b,
      visible: b.matches(':focus-visible'),
      style: cs.outlineStyle,
      width: parseFloat(cs.outlineWidth),
      color: cs.outlineColor,
    });
    b.blur();
  }
  return {accent, out};
}
"""


def test_ub_buttons_show_accent_focus_ring(mock_server, pw_browser):
    ctx, page, errors = _open_user_builds(pw_browser, mock_server, 1920, 920)
    try:
        # A keyboard press first so programmatic focus is keyboard-modality
        # (:focus-visible) in Chromium, as a Tab user would get.
        page.keyboard.press("Shift")
        m = page.evaluate(_FOCUS)
    finally:
        page.close()
        ctx.close()
    for f in m["out"]:
        assert not f.get("missing"), f
        assert f["focused"] and f["visible"], f
        assert f["style"] == "solid", f
        assert f["width"] >= 2, f
        assert f["color"] == m["accent"], (f, m["accent"])
    assert not errors, f"JS errors: {errors[:3]}"
