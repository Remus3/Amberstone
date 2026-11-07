"""
tests/snapshot_panels/test_overlay_phase_surfaces.py

RC-PHASE-SURFACES (MAIN ORDER 2215 item 9, RM-1272): one real-browser test per
game phase for the phase -> widget table in docs/OVERLAY_DOCTRINE.md section 10.
The table is read off disk here, so the doc and the page cannot drift apart: the
GIVEN side (one /api/state shape per phase) is a literal, the EXPECTED side comes
from the parsed row.

Shapes, cited from the code the page runs:
- lcu.phase: lcu/snapshot_shape.py capture_state, read by
  web/js/lib/overlay_phase.js overlayPhaseFromState.
- liveclient: dashboard/_liveclient.py, {} until a game answers on :2999.
- the page stamps the phase through renderTftOverlay (web/js/lib/overlay_tft.js),
  called from both live state sites in web/js/main.js, including under
  ?ui_mock=1, where the panels paint the fixture and the state stream carries the
  phase.
- web/js/lib/overlay_layout.js _internals._registry / LAUNCHER / _setHidden /
  _getLayout, the seams test_overlay_view.py already drives.

This is a MOCK capture (headless Chromium, ?ui_mock=1). The window column of the
table is pinned against rc-shell/src/overlay_state.js in
rc-shell/test/overlay_phase_contract.test.js; nothing here launches the shell. The
live half is OWED: the merger adds row RM-1272 to docs/LIVE_GAME_GATED_SYNC.md at
landing, and it does not exist before that.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from dashboard.view_router_state import derive_view, is_postgame_pgr_edge
from tests.snapshot_panels.conftest import _WS_STUB

ROOT = Path(__file__).resolve().parent.parent.parent
DOCTRINE = ROOT / "docs" / "OVERLAY_DOCTRINE.md"
PHASE_JS = ROOT / "web" / "js" / "lib" / "overlay_phase.js"
PHASE_TEST = ROOT / "web" / "js" / "lib" / "overlay_phase.test.mjs"
MAIN_JS = ROOT / "web" / "js" / "main.js"
SHELL_CONTRACT = ROOT / "rc-shell" / "test" / "overlay_phase_contract.test.js"
SCREENSHOTS = Path(__file__).parent / "screenshots"
_NODE = shutil.which("node")

_FEED = {"level": 6, "game_time_s": 120}
# /api/state.minimap_rect is mode-gated, not phase-gated (dashboard/_state_builder.py),
# so a pre-flipped mode_key carries it through the lobby and champ select.
_RECT = {"x": 1600, "y": 761, "w": 312, "h": 312, "flip": False,
         "source": "settings", "native_w": 2560, "native_h": 1440}

# The GIVEN half: what /api/state carries in each phase.
_STATE = {
    "lobby": {"mode_key": "sr", "lcu": {"phase": "Lobby"}, "liveclient": {},
              "minimap_rect": _RECT},
    "champ-select": {"mode_key": "sr", "lcu": {"phase": "ChampSelect"}, "liveclient": {},
                     "minimap_rect": _RECT},
    "loading": {"mode_key": "sr", "lcu": {"phase": "GameStart"}, "liveclient": {},
                "minimap_rect": _RECT},
    "in-game": {"mode_key": "sr", "lcu": {"phase": "InProgress"}, "liveclient": _FEED,
                "minimap_rect": _RECT},
    # The arm the field gate does observable work on today: :2999 still answers
    # after the LCU says the game ended, so the shell keeps the window up.
    "post-game": {"mode_key": "sr", "lcu": {"phase": "EndOfGame"}, "liveclient": _FEED,
                  "minimap_rect": _RECT},
}

# Reads every registry widget the page mounted, plus w-mmrect (settings-pinned,
# not in the registry; overlay.css carries its phase gate).
_READ_FIELD = """
async () => {
  const L = await import('/js/lib/overlay_layout.js');
  const out = {};
  const ws = L._internals._registry().concat([L._internals.LAUNCHER]);
  for (const w of ws) {
    const el = document.querySelector(w.sel);
    if (!el) continue;
    out[w.id] = {
      ovxHidden: el.classList.contains('ovx-hidden'),
      display: getComputedStyle(el).display,
    };
  }
  const mm = document.querySelector('#am-mmrect');
  if (mm) out['w-mmrect'] = {ovxHidden: false, display: getComputedStyle(mm).display};
  return out;
}
"""


def _doc_rows():
    """The section-10 fenced table, parsed off disk."""
    text = DOCTRINE.read_text(encoding="utf-8")
    start = text.index("## 10. PHASE SURFACES")
    end = text.find("\n## ", start + 1)
    section = text[start:] if end == -1 else text[start:end]
    body = section.split("```")[1].split("\n")[1:]
    assert body[0].split() == ["phase", "window", "companion", "field"]
    rows = {}
    for raw in body[2:]:
        if not raw.strip():
            continue
        phase, window, companion, field = re.split(r"\s{2,}", raw.strip())
        rows[phase] = {"window": window, "companion": companion, "field": field.split()}
    return rows


def _open_phase(pw_browser, mock_server, state, query="?ui_mock=1&mode=sr&overlay=1"):
    mock_server._store["data"] = state
    ctx = pw_browser.new_context(
        ignore_https_errors=True, viewport={"width": 1920, "height": 1080}
    )
    page = ctx.new_page()
    page.add_init_script(_WS_STUB)
    errors: list[str] = []
    page.on("pageerror", lambda err: errors.append(str(err)))
    page.goto(mock_server.url + "/" + query, wait_until="domcontentloaded", timeout=15_000)
    page.wait_for_function(
        "document.body.classList.contains('ovx-ready') && !!document.body.dataset.ovxPhase",
        timeout=10_000,
    )
    if state.get("minimap_rect"):
        # The renderers have to have RUN: before they do, the data-gated mounts
        # (w-mmrect above all) are display:none for a reason that is not the phase
        # gate, and a "hidden in this phase" read would pass on an empty page. A
        # mutation deleting the w-mmrect gate survived until this wait went in.
        page.wait_for_function(
            "(() => { const m = document.getElementById('am-mmrect');"
            " const c = document.querySelector('#am-call-body div');"
            " return !!m && !m.hidden && m.classList.contains('ovx-widget') && !!c; })()",
            timeout=10_000,
        )
    return ctx, page, errors


def _assert_row(phase, pw_browser, mock_server):
    """The page's field equals the doc row for this phase: every widget the row
    leaves out is off through the .ovx-hidden gate, every widget it names is on."""
    row = _doc_rows()[phase]
    ctx, page, errors = _open_phase(pw_browser, mock_server, _STATE[phase])
    try:
        assert page.evaluate("document.body.dataset.ovxPhase") == phase
        field = page.evaluate(_READ_FIELD)
        # Non-vacuous: the League registry really mounted, so an empty read
        # cannot pass, and the data-gated panes are not what is being graded.
        assert {"w-launcher", "w-call", "w-build", "w-lead", "w-stats"} <= set(field)
        for wid, read in field.items():
            allowed = row["field"] == ["all"] or wid in row["field"]
            if wid == "w-mmrect":
                # Off the registry; a CSS gate, not .ovx-hidden. The fixture ships
                # a minimap_rect, so in-game it paints: the positive control.
                assert (read["display"] != "none") is allowed, f"{wid} wrong in {phase}: {read}"
                continue
            assert read["ovxHidden"] is (not allowed), f"{wid} gate wrong in {phase}: {read}"
            if not allowed:
                assert read["display"] == "none", f"{wid} paints in {phase}: {read}"
        # The launcher (the escape hatch) and, where the row names them, the
        # primary panes actually paint - not just "not gated".
        assert field["w-launcher"]["display"] != "none"
        for wid in ("w-call", "w-build"):
            if row["field"] == ["all"] or wid in row["field"]:
                assert field[wid]["display"] != "none", f"{wid} must paint in {phase}"
        SCREENSHOTS.mkdir(exist_ok=True)
        page.screenshot(path=str(SCREENSHOTS / f"overlay_phase_{phase}.png"))
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{phase}]: {errors[:3]}"
    return field


def test_phase_lobby_shows_only_the_launcher(mock_server, pw_browser):
    field = _assert_row("lobby", pw_browser, mock_server)
    assert [w for w, r in field.items() if not r["ovxHidden"] and w != "w-mmrect"] == ["w-launcher"]


def test_phase_champ_select_shows_the_pregame_set(mock_server, pw_browser):
    field = _assert_row("champ-select", pw_browser, mock_server)
    # w-build is placed (its matchup card + draft-elo chip wait for the :2999
    # roster, so this is not a matchup answer; doctrine section 10).
    assert not field["w-build"]["ovxHidden"]
    assert field["w-objgauges"]["ovxHidden"], "a live-only cue must not show in champ select"


def test_phase_loading_shows_the_pregame_set(mock_server, pw_browser):
    field = _assert_row("loading", pw_browser, mock_server)
    assert not field["w-build"]["ovxHidden"]
    assert field["w-ovds"]["ovxHidden"], "the knob pane is champ-select only"


def test_phase_in_game_shows_the_whole_field(mock_server, pw_browser):
    field = _assert_row("in-game", pw_browser, mock_server)
    assert not [w for w, r in field.items() if r["ovxHidden"]], f"gated in-game: {field}"


def test_phase_post_game_shows_only_the_launcher(mock_server, pw_browser):
    field = _assert_row("post-game", pw_browser, mock_server)
    assert field["w-mmrect"]["display"] == "none", "the minimap outline must go too"
    assert [w for w, r in field.items() if not r["ovxHidden"] and w != "w-mmrect"] == ["w-launcher"]


def test_unknown_phase_fails_open_to_the_operator_field(mock_server, pw_browser):
    """No lcu.phase and no :2999 feed (an LCU blink, or the tick before the first
    state): no phase gate, so the panel a real game is showing never blinks off."""
    ctx, page, errors = _open_phase(pw_browser, mock_server, {})
    try:
        assert page.evaluate("document.body.dataset.ovxPhase") == "unknown"
        field = page.evaluate(_READ_FIELD)
        assert not [w for w, r in field.items() if r["ovxHidden"]], f"gated: {field}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [unknown]: {errors[:3]}"


def test_phase_gate_layers_under_the_operator_hidden_flag(mock_server, pw_browser):
    """The gate is computed, never stored: walking a game's phases leaves the
    layout store alone, an operator hide survives every phase, and a widget the
    phase turned off comes back on its own."""
    ctx, page, errors = _open_phase(pw_browser, mock_server, _STATE["in-game"])
    try:
        result = page.evaluate(
            """async (states) => {
                const L = await import('/js/lib/overlay_layout.js');
                const T = await import('/js/lib/overlay_tft.js');
                const I = L._internals;
                const w = (id) => I._registry().find((x) => x.id === id);
                const hid = (id) => document.querySelector(w(id).sel)
                    .classList.contains('ovx-hidden');
                I._setHidden(w('w-call'), true);
                const before = JSON.stringify(I._getLayout());
                const walk = {};
                for (const [name, st] of Object.entries(states)) {
                    T.renderTftOverlay(st);
                    walk[name] = {call: hid('w-call'), build: hid('w-build'),
                                  lead: hid('w-lead')};
                }
                return {walk, same: JSON.stringify(I._getLayout()) === before};
            }""",
            {k: _STATE[k] for k in ("lobby", "champ-select", "loading", "in-game", "post-game")},
        )
        assert result["same"], "a phase change must never write the layout store"
        for phase, read in result["walk"].items():
            assert read["call"] is True, f"the operator's hide must hold in {phase}"
        assert result["walk"]["champ-select"]["build"] is False
        assert result["walk"]["lobby"]["build"] is True
        assert result["walk"]["post-game"]["build"] is True
        assert result["walk"]["in-game"]["lead"] is False, "a phase-off widget must come back"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [layering]: {errors[:3]}"


def test_the_hidden_gate_beats_every_widget_display_rule(mock_server, pw_browser):
    """The .ovx-hidden gate has to win over each widget's own display rule, with
    the mount populated. `#rn-lead / #rn-choices / #rn-callouts:not([hidden])`
    carries display:flex !important at id specificity, so until its selector
    excluded .ovx-hidden those three kept painting through the phase gate, through
    the game-family gate AND through the operator's own per-widget hide. Every
    other test here saw them `hidden` by the data gate and could not tell. Found by
    the hint audit: a populated w-choices painted on the TFT field."""
    ctx, page, errors = _open_phase(pw_browser, mock_server, _STATE["lobby"])
    try:
        painted = page.evaluate(
            """async () => {
                const L = await import('/js/lib/overlay_layout.js');
                const out = {};
                for (const w of L._internals._registry()) {
                    const el = document.querySelector(w.sel);
                    if (!el) continue;
                    el.hidden = false;
                    const d = getComputedStyle(el).display;
                    if (d !== 'none') out[w.id] = d;
                }
                return out;
            }"""
        )
        assert painted == {}, f"painting through the lobby gate: {painted}"
        # And the operator's hide, in-game, populated: the pre-existing half.
        result = page.evaluate(
            """async (st) => {
                const L = await import('/js/lib/overlay_layout.js');
                const T = await import('/js/lib/overlay_tft.js');
                T.renderTftOverlay(st);
                const out = {};
                for (const id of ['w-lead', 'w-choices', 'w-callouts']) {
                    const w = L._internals._registry().find((x) => x.id === id);
                    const el = document.querySelector(w.sel);
                    el.hidden = false;
                    const shown = getComputedStyle(el).display;
                    L._internals._setHidden(w, true);
                    out[id] = [shown, getComputedStyle(el).display];
                }
                return out;
            }""",
            _STATE["in-game"],
        )
        for wid, (shown, hidden) in result.items():
            assert shown == "flex", f"{wid} must paint in-game when populated: {shown}"
            assert hidden == "none", f"{wid} ignores the operator's hide: {hidden}"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [hidden gate]: {errors[:3]}"


def test_tft_loading_then_in_game_gates_the_tft_set(mock_server, pw_browser):
    """TFT has nothing on :2999: GameStart is loading (launcher only, the League
    set is off by game family), InProgress is in-game, and the TFT set paints."""
    state = {"mode_key": "tft", "lcu": {"phase": "GameStart"}, "liveclient": {},
             "coach": {"stage": "1-2", "level": 3, "hp": 100, "gold": 8}}
    ctx, page, errors = _open_phase(pw_browser, mock_server, state, query="?overlay=1&mode=tft")
    try:
        assert page.evaluate("document.body.dataset.ovxPhase") == "loading"
        assert page.evaluate("document.body.dataset.ovxGame") == "tft"
        assert page.eval_on_selector("#ovt-hud", "e => e.classList.contains('ovx-hidden')"), (
            "the TFT vitals must wait for the game"
        )
        page.evaluate(
            """async (st) => {
                const T = await import('/js/lib/overlay_tft.js');
                T.renderTftOverlay(st);
            }""",
            dict(state, lcu={"phase": "InProgress"}),
        )
        assert page.evaluate("document.body.dataset.ovxPhase") == "in-game"
        assert not page.eval_on_selector("#ovt-hud", "e => e.classList.contains('ovx-hidden')")
        assert page.eval_on_selector("#ovt-hud", "e => getComputedStyle(e).display") != "none"
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [tft phases]: {errors[:3]}"


_READ_AUDIT = """
() => {
  const out = [];
  for (const el of document.querySelectorAll('.ovx-widget')) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || el.hidden) continue;
    const b = el.getBoundingClientRect();
    out.push({
      id: el.dataset.ovxId, tier: el.dataset.ovxTier || '',
      x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height),
      font: cs.fontSize, pointer: cs.pointerEvents,
      text: (el.innerText || '').slice(0, 400),
    });
  }
  return out;
}
"""

# doctrine header: U+26A0 warn, U+2713 check, U+25BA play are code, not prose.
_FUNCTIONAL_GLYPHS = {chr(0x26A0), chr(0x2713), chr(0x25BA)}


@pytest.mark.parametrize("phase", ["lobby", "champ-select", "loading", "in-game", "post-game"])
def test_phase_audit_capture(phase, mock_server, pw_browser):
    """The 5-phase UI audit per game phase, as a capture read back from the page
    (written beside the screenshots, gitignored). STRUCTURE: only the row's widgets
    paint. HIT-TARGETS: the launcher stays reachable. ASCII: all painted text.
    HIERARCHY: the out-of-game rows, which are short, do not overlap. TYPOGRAPHY of
    the hint lives in test_overlay_hotkey_hints.py; this slice adds no type."""
    row = _doc_rows()[phase]
    ctx, page, errors = _open_phase(pw_browser, mock_server, _STATE[phase])
    try:
        painted = page.evaluate(_READ_AUDIT)
    finally:
        page.close()
        ctx.close()
    assert not errors, f"JS errors [{phase}]: {errors[:3]}"
    SCREENSHOTS.mkdir(exist_ok=True)
    (SCREENSHOTS / f"overlay_phase_audit_{phase}.json").write_text(
        json.dumps(painted, indent=1), encoding="ascii", newline="\n"
    )
    ids = {p["id"] for p in painted}
    assert "w-launcher" in ids, painted
    if row["field"] != ["all"]:
        assert ids <= set(row["field"]), f"{phase}: {ids - set(row['field'])} paints off the row"
    launcher = next(p for p in painted if p["id"] == "w-launcher")
    assert launcher["w"] == 34 and launcher["h"] == 34, launcher
    for p in painted:
        stray = {c for c in p["text"] if ord(c) > 0x7F} - _FUNCTIONAL_GLYPHS
        assert not stray, f"{p['id']}: non-ASCII {stray}"
    if row["field"] != ["all"]:
        for i, a in enumerate(painted):
            for b in painted[i + 1:]:
                apart = (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"]
                         or a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])
                assert apart, f"{phase}: {a['id']} overlaps {b['id']}: {a} {b}"


def test_doc_companion_column_matches_the_view_router():
    """The companion column against dashboard/view_router_state.py, the pytest
    mirror of main.js _viewAutoDerive. The window column is rc-shell's contract."""
    rows = _doc_rows()
    assert set(rows) == {"lobby", "champ-select", "loading", "in-game", "post-game"}
    assert derive_view("Lobby", "sr", None, live=False).view == rows["lobby"]["companion"]
    assert derive_view("ChampSelect", "sr", None, live=False).view == rows["champ-select"]["companion"]
    assert derive_view("GameStart", "sr", "champ-select", live=False).view == rows["loading"]["companion"]
    # In-game the shell hides the dashboard window, so no view shows: that cell is a
    # window token, derived in rc-shell/test/overlay_phase_contract.test.js from
    # windowActionsWithPolicy (test_rc_shell_phase_contract_runs_under_node runs it).
    assert rows["in-game"]["companion"] == "hidden"
    # Post-game reaches its view through the one-shot PGR edge, which pins it as the
    # manual view; derive_view alone says home once the feed is gone. The view is the
    # one main.js saves on that edge, read off disk (RM-1272 residue: was a literal).
    assert is_postgame_pgr_edge("EndOfGame", "in-progress") is True
    assert rows["post-game"]["companion"] == _pgr_edge_view()


def _pgr_edge_view():
    """The view _viewAutoDerive saves on the game-end edge (web/js/main.js): the
    _viewSaveManual call that sits right before the edge's PGR fetch."""
    src = MAIN_JS.read_text(encoding="utf-8")
    hits = re.findall(
        r'_viewSaveManual\("([a-z-]+)"\);\s*\}\s*catch\s*\(_\)\s*\{\}\s*\n'
        r"\s*try\s*\{\s*fetchAndRenderLastMatch\(\);",
        src,
    )
    assert len(hits) == 1, f"the PGR edge's view save is not unique in main.js: {hits}"
    return hits[0]


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
def test_rc_shell_phase_contract_runs_under_node():
    """The window and companion-window columns are pinned in rc-shell; run that
    contract here too, so a pytest-only landing cannot leave it red."""
    done = subprocess.run(
        [_NODE, "--test", str(SHELL_CONTRACT)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT / "rc-shell"),
    )
    out = done.stdout + done.stderr
    assert done.returncode == 0, out[-2000:]
    assert re.search(r"pass [1-9]\d*", out), out[-500:]
    assert re.search(r"fail 0\b", out), out[-500:]
    # Non-vacuous: the derived in-game companion row ran.
    assert "doc row in-game: companion window hide" in out, out[-1500:]


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
def test_pure_phase_suite_runs_under_node():
    done = subprocess.run(
        [_NODE, "--test", str(PHASE_TEST)],
        capture_output=True, text=True, timeout=60, cwd=str(ROOT),
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    # An exit 0 from a runner that collected nothing would pass the line above.
    assert re.search(r"pass [1-9]\d*", done.stdout), done.stdout[-500:]
    assert re.search(r"fail 0\b", done.stdout), done.stdout[-500:]


@pytest.mark.parametrize("path", [PHASE_JS, PHASE_TEST, Path(__file__)])
def test_new_files_are_ascii_lf(path: Path):
    raw = path.read_bytes()
    assert not [b for b in raw if b > 0x7F], f"non-ASCII in {path.name}"
    assert b"\r" not in raw, f"CR in {path.name}"
