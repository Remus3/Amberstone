"""RM-1248 remainder - the shared-file writer inventories cite by symbol.

Five files carried an inventory of who writes data/force_scan.json and
root coaching_data.json, and who holds core.coaching_data_lock, by line:

  tests/test_coaching_data_lock.py          (module docstring)
  core/coaching_data_lock.py                (MEASURED HOLDERS, SCOPE,
                                             LIMITS, the _TL_TIMEOUT_S note)
  tests/test_polled_json_lane8_cycle24.py   (module docstring, W5)
  core/polled_json.py                       (_scratch_path docstring)
  coaches/arena_coach.py                    (the force_scan bump comment)

What the cites meant, in the tree each was written against (8bf931e29 for
the polled_json inventory, e2cc87e56 for the lock holders):

  core/hotkeys.py:103               -> _trigger_force_scan
  dashboard/_writers.py:68          -> force_vision_scan
  dashboard/_writers.py:60 / :63 / :73
                                    -> set_pregame (its lock / its write)
  coaches/arena_coach.py:481        -> Coach._on_state_received
  tools/lcu_agent.py:1372           -> _write_force_scan_marker
  coaches/_base_coach.py:465        -> BaseCoach._vision_loop (the reader)
  app/__init__.py:253 / :272        -> OverlayApp._init_data_file / _write_data
  app/__init__.py:42                -> the DATA_FILE assignment
  coach_integration/_coach.py:117   -> CoachIntegration.reset_state
  coach_integration/_coach.py:678 / :713 / :675-734
                                    -> CoachIntegration._write_fields
  dashboard/routes_state.py:637     -> _serve_command_post ("refresh")
  agents/supervisor.py:774          -> Supervisor._file_post_game_summary
  tests/test_p2w1_app_b.py:338 / :359
                                    -> test_reset_state_holds_coaching_data_lock

At HEAD (lane/repo, 2026-10-31) most had drifted (the lock holders by 3 to
238 lines, _write_force_scan_marker to 1527). Two claims had gone stale with
them: "exactly these four" holders (RM-277 added the two app/__init__.py
holders on 2026-10-03), and "_coach.py still hand-rolls its scratch name"
(RM-258 / RM-261 moved _write_fields onto core.polled_json). This guard pins:

(a) no line cite into any inventoried module in the five citer files;
(b) every named symbol still exists and still does what the prose says;
(c) the holder set of `with coaching_data_lock():` outside tests/ is exactly
    the six symbols the lock module names, so the inventory cannot go stale
    silently again;
(d) each citer names its symbols in a COMMENT or STRING token.

Other-family cites in the same files are out of this guard's scope on
purpose. The polled_json resolver cites (core/cost_tracker.py:490,
coaches/_base_coach.py:502 / :539, coaches/sr_user_builds.py:513, as
written at 8bf931e29) are now pinned by
tests/test_polled_json_resolver_cites_s144p51.py; the arena_coach /
aram_coach D-class cite coaches/_base_coach.py:66-68 is still open.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

from tests import _repo_walk

ROOT = Path(__file__).resolve().parent.parent

_HOLDERS = ("reset_state", "_write_fields", "set_pregame",
            "_serve_command_post", "_init_data_file", "_write_data")
_FORCE = ("_trigger_force_scan", "force_vision_scan", "_on_state_received",
          "_write_force_scan_marker", "_vision_loop")

# Each citer and the symbol names its prose must carry.
CITERS = {
    "tests/test_coaching_data_lock.py": _HOLDERS,
    "core/coaching_data_lock.py": _HOLDERS + (
        "_file_post_game_summary", "DATA_FILE",
        "test_reset_state_holds_coaching_data_lock"),
    "tests/test_polled_json_lane8_cycle24.py": _FORCE + (
        "_init_data_file", "_write_data", "set_pregame", "_write_fields"),
    # writers only: this inventory never named the reader
    "core/polled_json.py": _FORCE[:4] + (
        "_init_data_file", "_write_data", "set_pregame", "_write_fields"),
    "coaches/arena_coach.py": ("_trigger_force_scan", "force_vision_scan",
                               "_write_force_scan_marker"),
}

BANNED = re.compile(
    r"(?:\bhotkeys|\b_writers|\barena_coach|\blcu_agent|\broutes_state"
    r"|coach_integration/_coach|\bapp/__init__|\bagents/supervisor"
    r"|\btest_p2w1_app_b)\.py:\d"
    r"|\b_base_coach\.py:465\b")

# (file, qualified symbol, text its source must carry)
HOLDS = (
    ("core/hotkeys.py", "_trigger_force_scan", '"force_scan.json"'),
    ("dashboard/_writers.py", "force_vision_scan", '"data/force_scan.json"'),
    ("dashboard/_writers.py", "set_pregame", "with coaching_data_lock():"),
    ("dashboard/_writers.py", "set_pregame",
     'atomic_write_json("coaching_data.json"'),
    ("coaches/arena_coach.py", "Coach._on_state_received",
     '"force_scan.json"'),
    ("tools/lcu_agent.py", "_write_force_scan_marker", '"force_scan.json"'),
    ("coaches/_base_coach.py", "BaseCoach._vision_loop", '"force_scan.json"'),
    ("app/__init__.py", "OverlayApp._init_data_file",
     "_atomic_write_json(DATA_FILE"),
    ("app/__init__.py", "OverlayApp._write_data", "_atomic_write_json(DATA_FILE"),
    ("coach_integration/_coach.py", "CoachIntegration._write_fields",
     "atomic_write_text(self.data_file"),
    ("coach_integration/_coach.py", "CoachIntegration._write_fields",
     "for attempt in range(retries)"),
    ("agents/supervisor.py", "Supervisor._file_post_game_summary",
     '"coaching_data.json"'),
    ("tests/test_p2w1_app_b.py", "test_reset_state_holds_coaching_data_lock",
     "time.sleep(0.25)"),
)

EXPECTED_HOLDERS = {
    ("app/__init__.py", "OverlayApp._init_data_file"),
    ("app/__init__.py", "OverlayApp._write_data"),
    ("coach_integration/_coach.py", "CoachIntegration.reset_state"),
    ("coach_integration/_coach.py", "CoachIntegration._write_fields"),
    ("dashboard/_writers.py", "set_pregame"),
    ("dashboard/routes_state.py", "_serve_command_post"),
}


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _prose(rel: str) -> str:
    toks = tokenize.generate_tokens(io.StringIO(_src(rel)).readline)
    return "\n".join(t.string for t in toks
                     if t.type in (tokenize.COMMENT, tokenize.STRING))


def _symbol(rel: str, qual: str) -> str:
    src = _src(rel)
    node: ast.AST = ast.parse(src)
    for part in qual.split("."):
        found = [c for c in ast.iter_child_nodes(node)
                 if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)) and c.name == part]
        if not found:
            raise AssertionError(f"{rel}: {qual} not found - the inventory "
                                 "prose names it (RM-1248)")
        node = found[0]
    return ast.get_source_segment(src, node) or ""


def _lock_holders(rel: str) -> set[tuple[str, str]]:
    """(rel, qualified def) for every `with coaching_data_lock():` in rel."""
    out: set[tuple[str, str]] = set()

    def walk(node: ast.AST, stack: list[str]) -> None:
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
                walk(ch, stack + [ch.name])
                continue
            if isinstance(ch, (ast.With, ast.AsyncWith)):
                for item in ch.items:
                    call = item.context_expr
                    if (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Name)
                            and call.func.id == "coaching_data_lock"):
                        out.add((rel, ".".join(stack) or "<module>"))
            walk(ch, stack)

    walk(ast.parse(_src(rel)), [])
    return out


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_carries_no_inventory_line_cite(rel):
    hits = [(n, line.strip()) for n, line in enumerate(_src(rel).splitlines(), 1)
            if BANNED.search(line)]
    assert not hits, (
        f"{rel} cites a force_scan / coaching_data writer by line again; cite "
        f"the symbol (RM-1248): {hits}")


@pytest.mark.parametrize("rel", sorted(CITERS))
def test_citer_names_its_symbols_in_prose(rel):
    prose = " ".join(_prose(rel).split())
    missing = [s for s in CITERS[rel] if s not in prose]
    assert not missing, (
        f"{rel}: the inventory no longer names {missing} in a comment or "
        "docstring (RM-1248)")


@pytest.mark.parametrize(("rel", "qual", "text"), HOLDS,
                         ids=[f"{q}:{t[:20]}" for _, q, t in HOLDS])
def test_named_symbol_holds(rel, qual, text):
    assert text in _symbol(rel, qual), (
        f"{rel} {qual} no longer carries {text!r}; re-word the inventory "
        "prose that names it (RM-1248)")


def test_data_file_is_root_coaching_data():
    assert re.search(r'^DATA_FILE\s*=\s*SCRIPT_DIR / "coaching_data\.json"',
                     _src("app/__init__.py"), re.M)


def test_lock_holder_set_matches_the_inventory():
    _repo_walk.self_check(ROOT)
    found: set[tuple[str, str]] = set()
    for path in _repo_walk.iter_repo_files(ROOT, ("*.py",)):
        rel = _repo_walk.relative_posix(path, ROOT)
        if "tests" in rel.split("/") or rel == "core/coaching_data_lock.py":
            continue
        if "coaching_data_lock" not in path.read_text(encoding="utf-8",
                                                      errors="replace"):
            continue
        found |= _lock_holders(rel)
    assert found == EXPECTED_HOLDERS, (
        "the coaching_data_lock holder set changed; update MEASURED HOLDERS "
        "in core/coaching_data_lock.py, the tests/test_coaching_data_lock.py "
        f"docstring and this guard together. extra={found - EXPECTED_HOLDERS} "
        f"missing={EXPECTED_HOLDERS - found}")


def test_banned_pattern_still_bites():
    for sample in ("core/hotkeys.py:103", "dashboard/_writers.py:68",
                   "coaches/arena_coach.py:481", "tools/lcu_agent.py:1372",
                   "coaches/_base_coach.py:465", "app/__init__.py:253",
                   "coach_integration/_coach.py:713",
                   "dashboard/routes_state.py:637", "agents/supervisor.py:774",
                   "tests/test_p2w1_app_b.py:338"):
        assert BANNED.search(sample), sample
    for other in ("coaches/_base_coach.py:502", "coaches/_base_coach.py:66-68",
                  "core/cost_tracker.py:490"):
        assert not BANNED.search(other), other
