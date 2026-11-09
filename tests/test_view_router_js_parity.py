"""Differential parity: the Python view-router mirror against the REAL JS.

``dashboard/view_router_state.py`` is a TEST MIRROR of ``_viewAutoDerive`` and
``_viewIsUrgent`` in ``web/js/main.js``; its header says "if you change one,
change both". Until this file that contract was held only by convention plus
grep contracts over the JS source (tests/test_view_router_postgame_pgr_arm.py:
"there is no jsdom/node harness for web/js page code"), so every behavioural
test built on the mirror proved the MIRROR, not the runtime.

This test slices both functions out of main.js by marker, runs them under
node with the four page globals they read stubbed (``state``, ``_VIEW``,
``activeMatchEnabled``, ``_viewSaveManual``; ``fetchAndRenderLastMatch`` and
``setTimeout`` are inert), and compares, for every case of an exhaustive
per-tick grid, the derived view, the new sticky and whether the game-end PGR
edge fired, against ``derive_view`` / ``is_postgame_pgr_edge`` / ``is_urgent``.
The tick is pure given the prior sticky, so the grid covers every transition.

The grid deliberately includes JSON values that are not strings (``0``,
``false``, ``true``, ``[]``, ``{}``, a list), because ``lcu.phase`` and
``state.mode`` are read straight off a polled ``/api/state`` body. JS
truthiness differs from Python's there (``[]`` and ``{}`` are truthy in JS) and
JS ``===`` / ``includes`` never raise, so the mirror must follow JS semantics
or it silently stops being a mirror on exactly the malformed input that
tests most need to model (S144-T-685).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dashboard.view_router_state import (  # noqa: E402
    derive_view,
    is_postgame_pgr_edge,
    is_urgent,
)

MAIN_JS = REPO / "web" / "js" / "main.js"
_NODE = shutil.which("node")
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Every LCU gameflow phase the client is documented to emit, plus junk.
_LCU_PHASES = [
    "None", "Lobby", "Matchmaking", "ReadyCheck", "ChampSelect", "GameStart",
    "InProgress", "WaitingForStats", "PreEndOfGame", "EndOfGame",
    "TerminatedInError", "Reconnect", "FailedToLaunch",
    "CheckedIntoTournament",
]
_JUNK = [None, "", 0, False, True, 7, [], {}, ["Lobby"], {"phase": "x"}]
PHASES = _LCU_PHASES + ["inprogress", "lobby"] + _JUNK
MODES = [
    "client", "lobby", "sr", "aram", "arena", "brawl", "tft", "SR", "urf",
    None, "", 0, False, [], {}, ["sr"],
]
PRIORS = [None, "champ-select", "in-progress"]
VIEWS = [
    "home", "lobby", "champ-select", "active-match", "last-match",
    "historical-pgr", "", None, 0, [],
]


def _slice(src: str, head: str, nxt: str) -> str:
    i = src.find(head)
    assert i != -1, f"{head!r} not found in main.js"
    j = src.find(nxt, i)
    assert j != -1, f"{nxt!r} (next sibling) not found after {head!r}"
    return src[i:j]


def _js_functions() -> str:
    src = MAIN_JS.read_text(encoding="utf-8")
    derive = _slice(src, "function _viewAutoDerive(lcu, mode) {",
                    "\n  function _viewIsUrgent")
    urgent = _slice(src, "function _viewIsUrgent(targetView) {",
                    "\n  function applyView")
    return derive + "\n" + urgent


_HARNESS = r"""
"use strict";
const state = { latest: { liveclient: {} } };
const _VIEW = { gameStarted: null, current: "home", manual: null };
let _amEnabled = true;
let _saved = [];
function activeMatchEnabled() { return _amEnabled; }
function _viewSaveManual(id) { _saved.push(id); }
function fetchAndRenderLastMatch() {}
function setTimeout() {}
%FUNCS%
const input = JSON.parse(require("fs").readFileSync(0, "utf8"));
const derived = input.cases.map(function (c) {
  const lcuNull = c[0], phase = c[1], mode = c[2];
  _VIEW.gameStarted = c[3];
  _amEnabled = c[4];
  state.latest.liveclient = c[5] ? { gameData: { gameTime: 1 } } : {};
  _saved = [];
  const view = _viewAutoDerive(lcuNull ? null : { phase: phase }, mode);
  return [view, _VIEW.gameStarted, _saved.slice()];
});
const urgent = input.views.map(function (v) { return _viewIsUrgent(v); });
process.stdout.write(JSON.stringify({ derived: derived, urgent: urgent }));
"""


def _cases() -> list[list]:
    out: list[list] = []
    for phase in PHASES:
        for mode in MODES:
            for prior in PRIORS:
                for am in (True, False):
                    for live in (True, False):
                        out.append([False, phase, mode, prior, am, live])
    # lcu itself null (phase undefined in JS, None in the mirror).
    for mode in MODES:
        for prior in PRIORS:
            for am in (True, False):
                for live in (True, False):
                    out.append([True, None, mode, prior, am, live])
    return out


def _run_js(cases: list[list], tmp_path: Path) -> dict:
    script = tmp_path / "view_router_harness.js"
    script.write_bytes(
        _HARNESS.replace("%FUNCS%", _js_functions()).encode("utf-8"))
    done = subprocess.run(
        [_NODE, str(script)],
        input=json.dumps({"cases": cases, "views": VIEWS}),
        capture_output=True, text=True, timeout=120,
        creationflags=_CREATE_NO_WINDOW,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    return json.loads(done.stdout)


def _py(case: list) -> list:
    _lcu_null, phase, mode, prior, am, live = case
    try:
        r = derive_view(phase, mode, prior,
                        active_match_enabled=am, live=live)
        edge = is_postgame_pgr_edge(phase, prior)
    except Exception as exc:  # noqa: BLE001 - recorded as a parity miss
        return [f"raise:{type(exc).__name__}", None, []]
    return [r.view, r.game_started, ["last-match"] if edge else []]


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
def test_python_mirror_matches_the_real_js_on_every_tick(tmp_path):
    cases = _cases()
    js = _run_js(cases, tmp_path)
    assert len(js["derived"]) == len(cases)
    misses = []
    for case, want in zip(cases, js["derived"]):
        got = _py(case)
        if got != want:
            misses.append((case, "py", got, "js", want))
    assert not misses, (
        f"{len(misses)}/{len(cases)} ticks diverge; first 12: {misses[:12]}")


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
def test_is_urgent_matches_the_real_js(tmp_path):
    js = _run_js([], tmp_path)
    got = [is_urgent(v) for v in VIEWS]
    assert got == js["urgent"], list(zip(VIEWS, got, js["urgent"]))


@pytest.mark.skipif(_NODE is None, reason="node not on PATH")
def test_grid_is_not_vacuous(tmp_path):
    """Every one of the five auto-derive views, both sticky values and the
    PGR edge must actually occur in the JS results, so a harness that stubbed
    the function into a constant could not pass the parity test above."""
    js = _run_js(_cases(), tmp_path)
    views = {row[0] for row in js["derived"]}
    assert views == {"home", "lobby", "champ-select", "active-match",
                     "last-match"}, views
    stickies = {row[1] for row in js["derived"]}
    assert stickies == {None, "champ-select", "in-progress"}, stickies
    assert any(row[2] == ["last-match"] for row in js["derived"])


# Named regressions, one per finding, runnable without node.

def test_unhashable_phase_or_mode_derives_a_view_instead_of_raising():
    # Pre-fix: TypeError: unhashable type ('in frozenset').
    assert derive_view([], "sr", None).view == "last-match"
    assert derive_view({}, "sr", "in-progress").view == "active-match"
    assert derive_view(None, ["sr"], None).view == "last-match"
    assert derive_view("Lobby", {}, None).view == "lobby"
    assert is_postgame_pgr_edge([], "in-progress") is False
    assert is_postgame_pgr_edge({"p": 1}, "in-progress") is False


def test_falsy_non_string_mode_is_home_like_js_not_mode():
    # JS: `!mode` is true for 0 / false. Pre-fix the mirror said last-match.
    assert derive_view("None", 0, None).view == "home"
    assert derive_view("None", False, None).view == "home"


def test_empty_list_or_dict_phase_is_truthy_like_js():
    # JS `![]` / `!{}` are false, so neither arms the null-phase promotion.
    r = derive_view([], "arena", None, live=True)
    assert (r.view, r.game_started) == ("last-match", None)
    r = derive_view({}, "arena", "champ-select", live=True)
    assert (r.view, r.game_started) == ("champ-select", "champ-select")
    # A real null still does (characterization of the item-281 arm).
    r = derive_view(None, "arena", None, live=True)
    assert (r.view, r.game_started) == ("active-match", "in-progress")


def test_js_falsy_and_is_one_of_follow_js():
    from dashboard.view_router_state import _is_one_of, _js_falsy
    for v in (None, False, "", 0, 0.0, -0.0, float("nan")):
        assert _js_falsy(v) is True, v
    for v in (True, "0", " ", 1, -1, 0.5, [], {}, [0], "None"):
        assert _js_falsy(v) is False, v
    assert _is_one_of("Lobby", frozenset({"Lobby"})) is True
    assert _is_one_of(["Lobby"], frozenset({"Lobby"})) is False
    assert _is_one_of({"Lobby": 1}, ("Lobby",)) is False
    assert _is_one_of(None, frozenset({"Lobby"})) is False


def test_harness_slices_are_marker_anchored():
    funcs = _js_functions()
    assert re.search(r"^function _viewAutoDerive\(lcu, mode\) \{", funcs)
    assert "function _viewIsUrgent(targetView) {" in funcs
    assert "function applyView" not in funcs


def test_new_file_is_ascii_lf():
    raw = Path(__file__).read_bytes()
    assert not [b for b in raw if b > 0x7F]
    assert b"\r" not in raw
