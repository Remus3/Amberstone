"""S144-P-342 - every production dynamic module load is a named site with a stated target source.

``importlib.import_module``, ``__import__``, ``importlib.reload`` and ``spec_from_file_location`` run code chosen at run
time. In a tree whose loops and dashboard routes load sibling modules by path (to survive a missing package on
``sys.path``) the one question that matters is where the NAME or PATH comes from: a literal or repo-relative path is a
module-binding convenience; a value from a request, a config file or a data file is code execution. Nothing forced such
a site to be written down. Measured 2026-11-07 by AST over every tracked production ``.py`` (outside ``tests/``,
``docs/`` and the vendored ``ops/fleet_kit/``): 68 calls, each its own ``(file, call, scope)`` site, listed in ``_SITES``
(69 since S144-Q-123 added the sibling sweep's core/log_rotation load, 70 with headless_env's).

Result of the measurement: every target is one of
- ``LITERAL`` - a string / path literal, or a module constant, at the call;
- ``SIBLING`` - a parameter of a small binder whose every in-file caller passes a literal (checked 2026-11-07);
- ``ALLOWLIST`` - a name filtered against a frozen allowlist before the call;
- ``TABLE`` - a name read from a literal in-repo table;
- ``OPERATOR`` - a value the operator types on a command line (one site, a plug-in hook of an offline CLI).
No site takes its target from the network, the Live Client, the LCU, an HTTP request or a data file.

Detector: a call whose dotted name (spelled ``importlib.import_module``, ``from importlib import import_module``,
``import importlib.util as ilu`` ... resolved through the file's own imports) is in ``_LOAD_CALLS``. A hit is keyed
``(file, short call name, scope)``, scope being ``"module"`` or the enclosing function's dotted qualname. The set is
exact: a new site fails until it is added with a target source, and a site that goes away must be dropped. This
census also pins the two inline ``__import__('time')`` / ``__import__('json')`` spellings out of the tree except the one
frozen ``main.py`` row.

Named blind spots (measured absent 2026-11-07): ``getattr(importlib, "import_module")``, a loader held in a variable,
``importlib.machinery.SourceFileLoader`` / ``exec(compile(...))`` (the bare eval / exec guard owns the latter), and a
file that fails to parse (skipped, as in the sibling censuses).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_SKIP_PREFIXES = ("tests/", "docs/", "ops/fleet_kit/")

_LOAD_CALLS = frozenset({
    "importlib.import_module", "importlib.reload", "importlib.util.spec_from_file_location",
    "importlib.machinery.SourceFileLoader", "__import__", "imp.load_source", "imp.load_module",
    "runpy.run_path", "runpy.run_module",
})

_LITERAL = "LITERAL: a string / path literal or a module constant at the call"
_SIBLING = "SIBLING: a binder parameter; every in-file caller passes a literal"
_POLY = "LITERAL: the repo's own core/polled_json.py, located from __file__, bound once under a private name"

# (file, short call name, scope) -> where the module name or path comes from.
_SITES = {
    ("app/_game_lifecycle.py", "import_module", "GameLifecycleManager.on_game_start"):
        "TABLE: the module path is a value of core.coach_registry.MODE_COACH_MAP, a literal in-repo table",
    ("dashboard/routes_loop_control.py", "import_module", "_interrupt"): _LITERAL,
    ("dashboard/routes_loop_control.py", "import_module", "_lanes"): _LITERAL,
    ("dashboard/routes_loop_control.py", "import_module", "_launcher"): _LITERAL,
    ("dashboard/routes_loop_control.py", "import_module", "_steer"): _LITERAL,
    ("dashboard/routes_loop_status.py", "import_module", "_lanes"): _LITERAL,
    ("dashboard/routes_loop_status.py", "import_module", "_lanes_available"): _LITERAL,
    ("dashboard/routes_loop_status.py", "import_module", "_steer_summary"): _LITERAL,
    ("main.py", "__import__", "module"):
        "LITERAL: frozen file; an inline __import__('json') for the one config read at start-up",
    ("ops/audit/p7_arena_boots_regen.py", "spec_from_file_location", "_load_flatgen"):
        "LITERAL: tools/daemon_slayer_build_orders_generate.py under the repo root, one-shot audit script",
    ("ops/launcher/service_host.py", "spec_from_file_location", "_first_run_module"): _LITERAL,
    ("ops/launcher/service_host.py", "spec_from_file_location", "_updater_module"): _LITERAL,
    ("ops/launcher/update_cycle.py", "import_module", "_sibling"): _SIBLING,
    ("ops/launcher/update_cycle.py", "spec_from_file_location", "_sibling"): _SIBLING,
    ("ops/loop/adjudicator.py", "spec_from_file_location", "module"): _POLY,
    ("ops/loop/adjudicator.py", "spec_from_file_location", "_fleet_route_module"): _LITERAL,
    ("ops/loop/claude_stub.py", "spec_from_file_location", "module"): _POLY,
    ("ops/loop/done_sentinel.py", "spec_from_file_location", "module"): _POLY,
    ("ops/loop/drain_waves_2_3.py", "spec_from_file_location", "_load_by_path"): _SIBLING,
    ("ops/loop/executor.py", "spec_from_file_location", "_fleet_route_module"): _LITERAL,
    ("ops/loop/fleet_route.py", "spec_from_file_location", "_load"): _SIBLING,
    ("ops/loop/headless_env.py", "spec_from_file_location", "_log_rotation"):
        "LITERAL: the module constant _LOG_ROTATION_FILE, this checkout's core/log_rotation.py from __file__ (S144-Q-123)",
    ("ops/loop/inbox_tick.py", "import_module", "_bind_kit"): _SIBLING,
    ("ops/loop/inbox_tick.py", "spec_from_file_location", "_bind_kit"): _SIBLING,
    ("ops/loop/inbox_tick.py", "spec_from_file_location", "module"): _POLY,
    ("ops/loop/intents.py", "spec_from_file_location", "module"): _POLY,
    ("ops/loop/intents.py", "spec_from_file_location", "_refuse_if_gated"): _LITERAL,
    ("ops/loop/interrupt.py", "import_module", "_bind"): _SIBLING,
    ("ops/loop/interrupt.py", "spec_from_file_location", "_bind"): _SIBLING,
    ("ops/loop/lane_launcher.py", "import_module", "_inbox_mod"): _LITERAL,
    ("ops/loop/lane_launcher.py", "import_module", "_load_lanes"): _LITERAL,
    ("ops/loop/lane_launcher.py", "import_module", "_progress_mod"): _LITERAL,
    ("ops/loop/lane_launcher.py", "spec_from_file_location", "_inbox_mod"): _LITERAL,
    ("ops/loop/lane_launcher.py", "spec_from_file_location", "_load_lanes"): _LITERAL,
    ("ops/loop/lane_launcher.py", "spec_from_file_location", "_progress_mod"): _LITERAL,
    ("ops/loop/lane_progress.py", "import_module", "_bind_kit"): _SIBLING,
    ("ops/loop/lane_progress.py", "spec_from_file_location", "_bind_kit"): _SIBLING,
    ("ops/loop/lane_run_ledger.py", "spec_from_file_location", "module"): _POLY,
    ("ops/loop/lanes.py", "import_module", "_bind_core"): _SIBLING,
    ("ops/loop/lanes.py", "import_module", "_bind_kit_lanes"): _LITERAL,
    ("ops/loop/lanes.py", "spec_from_file_location", "_bind"): _SIBLING,
    ("ops/loop/lanes.py", "spec_from_file_location", "_bind_core"): _SIBLING,
    ("ops/loop/lanes.py", "spec_from_file_location", "_bind_kit_lanes"): _LITERAL,
    ("ops/loop/loop_controller.py", "spec_from_file_location", "_bind"): _SIBLING,
    ("ops/loop/loop_controller.py", "spec_from_file_location", "_bind_path"): _SIBLING,
    ("ops/loop/loop_controller.py", "spec_from_file_location", "module"): _LITERAL,
    ("ops/loop/queue_loop.py", "import_module", "_bind"): _SIBLING,
    ("ops/loop/queue_loop.py", "spec_from_file_location", "_bind"): _SIBLING,
    ("ops/loop/repo_review.py", "spec_from_file_location", "_load_by_path"): _SIBLING,
    ("ops/loop/steer.py", "spec_from_file_location", "_bind"): _SIBLING,
    ("ops/loop/steer.py", "spec_from_file_location", "_bind_path"): _SIBLING,
    ("ops/rc_dev_runtime.py", "import_module", "DevRuntime._reload_modules"):
        "ALLOWLIST: frozen file; callers filter the requested names against SAFE_RELOAD_MODULES before the call",
    ("ops/rc_dev_runtime.py", "reload", "DevRuntime._reload_modules"):
        "ALLOWLIST: frozen file; same SAFE_RELOAD_MODULES-filtered names, an already-imported module only",
    ("tools/ascii_escape_py.py", "spec_from_file_location", "_gate"): _LITERAL,
    ("tools/bot_merge_check.py", "spec_from_file_location", "_kit_module"): _SIBLING,
    ("tools/ci_watchdog.py", "spec_from_file_location", "_kit_module"): _SIBLING,
    ("tools/landing_sampler.py", "import_module", "_kit"): _SIBLING,
    ("tools/precommit_gate.py", "spec_from_file_location", "_ascii_rule"):
        "LITERAL: the sibling ASCII rule file next to this gate, located from __file__",
    ("tools/progress_watch.py", "import_module", "_steer_module"): _LITERAL,
    ("tools/progress_watch.py", "spec_from_file_location", "_kit"): _LITERAL,
    ("tools/progress_watch.py", "spec_from_file_location", "_steer_module"): _LITERAL,
    ("tools/rc_facts.py", "spec_from_file_location", "_load_inbox_tick"): _LITERAL,
    ("tools/replay_session.py", "import_module", "discover_events_source"): _LITERAL,
    ("tools/session_checklist.py", "spec_from_file_location", "_load"): _SIBLING,
    ("tools/session_steer.py", "import_module", "_load_steer"): _LITERAL,
    ("tools/session_steer.py", "spec_from_file_location", "_load_steer"): _LITERAL,
    ("tools/sibling_name_sweep.py", "spec_from_file_location", "_log_rotation"):
        "LITERAL: the module constant _LOG_ROTATION_FILE, this checkout's core/log_rotation.py from __file__ (S144-Q-123)",
    ("tools/slot_bucket_audit.py", "spec_from_file_location", "_load_slots"): _LITERAL,
    ("tools/tft_cv_accuracy.py", "import_module", "load_extractor"):
        "OPERATOR: --extractor package.module:function typed on the command line of an offline accuracy CLI",
    ("tools/truth_gate.py", "spec_from_file_location", "_kit_module"): _SIBLING,
}


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Name):
        return node.id
    return None


def _aliases(tree: ast.AST) -> dict[str, str]:
    """local name -> the dotted module path it stands for, from this file's own imports."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _resolve(name: str, aliases: dict[str, str]) -> str:
    head, _, rest = name.partition(".")
    real = aliases.get(head, head)
    return f"{real}.{rest}" if rest else real


def _scan(source: str) -> list[tuple[str, int, str]]:
    """``(short call name, lineno, scope)`` per dynamic load; scope is "module" or a function qualname."""
    tree = ast.parse(source)
    aliases = _aliases(tree)
    hits: list[tuple[str, int, str]] = []

    def visit(node: ast.AST, scope: list[str], in_fn: bool) -> None:
        for child in ast.iter_child_nodes(node):
            s, f = scope, in_fn
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                s, f = [*scope, child.name], True
            elif isinstance(child, ast.ClassDef):
                s = [*scope, child.name]
            if isinstance(child, ast.Call):
                d = _dotted(child.func)
                if d is not None:
                    d = _resolve(d, aliases)
                    if d in _LOAD_CALLS:
                        hits.append((d.rsplit(".", 1)[-1], child.lineno, ".".join(scope) if in_fn else "module"))
            visit(child, s, f)

    visit(tree, [], False)
    return sorted(hits, key=lambda h: (h[1], h[0]))


def _production_files():
    return [p for p in repo_files(REPO_ROOT, ("*.py",))
            if not relative_posix(p).startswith(_SKIP_PREFIXES) and "/tests/" not in relative_posix(p)]


def _found() -> tuple[set[tuple[str, str, str]], int]:
    found: set[tuple[str, str, str]] = set()
    calls = 0
    for p in _production_files():
        try:
            hits = _scan(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = relative_posix(p)
        calls += len(hits)
        found.update((rel, name, scope) for name, _line, scope in hits)
    return found, calls


def test_every_production_dynamic_load_is_a_named_site():
    assert len(_production_files()) > 100, "the tracked-file walk returned almost nothing"
    found, calls = _found()
    assert len(found) >= 40, "the walk saw almost no site, so an empty difference proves nothing"
    new = sorted(found - set(_SITES))
    gone = sorted(set(_SITES) - found)
    assert not new, f"new dynamic module load (add it to _SITES with its target source): {new}"
    assert not gone, f"stale _SITES entry (drop it): {gone}"
    assert calls == 70, f"call count moved to {calls}; a second call in a listed scope needs a look"


def test_every_site_names_its_target_source():
    kinds = ("LITERAL:", "SIBLING:", "ALLOWLIST:", "TABLE:", "OPERATOR:")
    assert all(why.startswith(kinds) and len(why) > 20 for why in _SITES.values())


def test_only_one_site_takes_its_target_from_the_operator():
    assert [k for k, why in _SITES.items() if why.startswith("OPERATOR:")] == [
        ("tools/tft_cv_accuracy.py", "import_module", "load_extractor")]


def test_the_only_inline_dunder_import_is_the_frozen_main_row():
    found, _ = _found()
    assert sorted(k for k in found if k[1] == "__import__") == [("main.py", "__import__", "module")]


def test_the_detector_flags_each_shape():
    cases = {
        "import importlib\nimportlib.import_module('a')\n": [("import_module", 2, "module")],
        "from importlib import import_module as im\ndef f(n):\n    return im(n)\n": [("import_module", 3, "f")],
        "import importlib.util as ilu\nclass C:\n    def m(self):\n        ilu.spec_from_file_location('n', p)\n":
            [("spec_from_file_location", 4, "C.m")],
        "import importlib\ndef g():\n    importlib.reload(m)\n": [("reload", 3, "g")],
        "x = __import__('json')\n": [("__import__", 1, "module")],
        "import runpy\nrunpy.run_path('x.py')\n": [("run_path", 2, "module")],
        "class K:\n    y = __import__('os')\n": [("__import__", 2, "module")],
    }
    for src, want in cases.items():
        assert _scan(src) == want, src


def test_the_detector_ignores_strings_comments_and_unrelated_names():
    clean = (
        "import importlib\n"
        "doc = 'importlib.import_module(x)'\n"
        "# __import__('os')\n"
        "def import_module(n):\n    return n\n"
        "import_module('x')\n"
        "name = importlib.__name__\n"
    )
    assert _scan(clean) == []


def test_restart_trigger_payload_still_carries_a_utc_stamp(tmp_path, monkeypatch):
    """The cleanup replaced an inline ``__import__('time')`` with an import: the payload is unchanged."""
    import re

    from agents.agent7_context import input_parser as ip

    monkeypatch.setattr(ip, "_PROJECT_ROOT", tmp_path)
    parser = ip.InputParser.__new__(ip.InputParser)
    result = parser.parse("restart rc")
    assert result.intent == "restart_rc"
    body = (tmp_path / "restart_trigger.txt").read_text(encoding="utf-8")
    assert re.fullmatch(r"user-request-\d{8}T\d{6}Z", body), body


def test_replay_chain_watch_needs_mine_reads_the_rates_file(tmp_path, monkeypatch):
    from tools import replay_chain_watch as rcw

    rates = tmp_path / "rates.json"
    monkeypatch.setattr(rcw, "RATES", rates)
    monkeypatch.setattr(rcw, "timelines_count", lambda: 5)
    rates.write_text('{"matches": 5}', encoding="utf-8")
    assert rcw.needs_mine() is False
    rates.write_text('{"matches": 4}', encoding="utf-8")
    assert rcw.needs_mine() is True
    rates.write_text("not json", encoding="utf-8")
    assert rcw.needs_mine() is True
