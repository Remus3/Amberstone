# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v18 - RACE GUARDS: the test-isolation guard (FLEET-COMMON 16).

Vendored byte-for-byte at ops/fleet_kit/ and pinned by MANIFEST.json. Do NOT
edit a vendored copy: report the defect to MAIN.

Why: a test that writes into the tree's LIVE state (control files, inbox,
outbox, progress) corrupts what the running sessions read, and nobody sees it
until a session acts on the bad byte. Pattern from a sibling tree's "left as
found" session guard plus its autouse tmp-root fixture.

A tree's tests/conftest.py installs it (no pytest_plugins needed):

    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ops" / "fleet_kit"))
    import fleet_test_guard
    fleet_test_guard.install(globals(), root=Path(__file__).resolve().parents[1],
                             env_roots={"MY_TREE_STATE_DIR": "state"})

install() adds two autouse fixtures to the conftest namespace:
  * _fleet_live_state_guard (session): snapshots every file under `watch`
    (default WATCH, relative to root) before the session and FAILS the session
    if a pre-existing file changed or vanished, or a new file appeared outside
    `inflow` (default INFLOW: other trees deliver into the inbox mid-run).
    `ignore` globs (default IGNORE: ledgers, progress, claims, locks, lanes and
    the other files live hooks rewrite while a suite runs) are skipped. The
    message carries counts and tree-relative paths only.
    v14 (SS 2239 a): IGNORE also holds every `*.lock` and the kit's own run
    budget file (ops/loop/control/headless_budget.json), which a scheduled
    tick rewrites while a suite runs. A tree whose tick rewrites OTHER watched
    files (a responder state file, a directive) passes them in
    `extra_ignore=(...)`, which ADDS to IGNORE instead of restating it.
  * _fleet_runtime_roots (function): for each {ENV_VAR: subpath} in
    env_roots, sets ENV_VAR to tmp_path/subpath, so code that resolves a
    runtime root from the environment writes under tmp. Requests tmp_path
    only when env_roots is non-empty.
    NOTE (v14, SS 2239 b): with env_roots non-empty this autouse fixture
    requests tmp_path for EVERY test, so it is in every test's fixture
    closure: `"tmp_path" in request.fixturenames` is always True. A test or
    fixture that branches on request.fixturenames must not use tmp_path as
    its signal.
    v21 (CS FIX 2026-10-19-2356 item 1): the kit's autouse fixtures never
    request the shared monkeypatch; each patches through its own private
    pytest.MonkeyPatch(), undone at that fixture's own teardown, and
    _fleet_runtime_roots requests tmp_path BEFORE it patches, so tmp_path's
    teardown never runs while the kit's patches are live.
    v21 (items 2 and 3): IGNORE holds fleet_board's render state
    (ops/loop/control/board/state.json and status.json), and no ignore glob
    hides a path the tree declares in ops/stop_sentinels.json: a declared
    stop sentinel created, changed or removed by a suite always fails it.
    v23: IGNORE adds ops/loop/control/board/board.html (the local board).
env FLEET_TEST_GUARD=off disables both (never in a gate run).

v16 (KIT-16), OPT-IN: budget(seconds) for a timing test. It returns
seconds x the number of LIVE suite-gate slot holders on the box right now
(at least 1, at most fleet_suite_gate.MAX_SLOTS), so a time budget written
for an idle box widens while other trees' suites share the CPU:

    assert elapsed < fleet_test_guard.budget(2.0)

Holders are the gate's slot files (fleet_suite_gate.held(gate_dir()));
a dead or reused holder does not count. No psutil, no load sampling; any
error reading the gate dir answers factor 1. load_factor() is the factor.
"""

import fnmatch
import os
from pathlib import Path

import pytest

WATCH = ("ops/loop/control", "moon_sync_inbox", "moon_sync_outbox")
INFLOW = ("moon_sync_inbox",)
IGNORE = ("*.jsonl", "*.tmp", "*.log", "ops/loop/control/progress/*",
          "ops/loop/control/claims/*", "ops/loop/control/locks/*",
          "ops/loop/control/lanes/*", "ops/loop/control/inbox_status.json",
          "ops/loop/control/session_done*", "ops/loop/control/governor/*",
          "*.lock", "ops/loop/control/headless_budget.json",
          "ops/loop/control/board/state.json", "ops/loop/control/board/status.json",
          "ops/loop/control/board/board.html")
SENTINELS_REL = "ops/stop_sentinels.json"  # = fleet_headless.SENTINELS_REL
SHOW = 5


def declared_sentinels(root):
    """v21: the tree-relative stop sentinel paths ops/stop_sentinels.json
    declares ({"paths": [...]}), lowercased; empty when absent or unreadable
    (the kit's spawn already fails closed on an unreadable file)."""
    import json
    try:
        doc = json.loads((Path(root) / SENTINELS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError):
        return frozenset()
    rels = doc.get("paths") if isinstance(doc, dict) else None
    if not isinstance(rels, list):
        return frozenset()
    return frozenset(Path(r).as_posix().lower() for r in rels if isinstance(r, str) and r)


def snapshot(root, watch=WATCH, ignore=IGNORE):
    """{relpath: (size, mtime_ns)} for every watched, non-ignored file. A
    declared stop sentinel (v21) is never ignored."""
    root = Path(root)
    keep = declared_sentinels(root)
    out = {}
    for w in watch:
        base = root / w
        if not base.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                p = Path(dirpath) / name
                rel = p.relative_to(root).as_posix()
                if rel.lower() not in keep and \
                        any(fnmatch.fnmatchcase(rel.lower(), g.lower()) for g in ignore):
                    continue
                try:
                    st = p.stat()
                except OSError:
                    continue
                out[rel] = (st.st_size, st.st_mtime_ns)
    return out


def compare(before, after, inflow=INFLOW):
    """(changed, deleted, created) relpath lists; inflow creations allowed."""
    changed = sorted(r for r in before if r in after and after[r] != before[r])
    deleted = sorted(r for r in before if r not in after)
    created = sorted(r for r in after if r not in before
                     and not any(r == i or r.startswith(i.rstrip("/") + "/") for i in inflow))
    return changed, deleted, created


def verdict(changed, deleted, created):
    """'' when clean, else a one-line failure message."""
    parts = []
    for word, rows in (("changed", changed), ("deleted", deleted), ("created", created)):
        if rows:
            more = f" +{len(rows) - SHOW} more" if len(rows) > SHOW else ""
            parts.append(f"{word} {len(rows)} ({', '.join(rows[:SHOW])}{more})")
    if not parts:
        return ""
    return ("fleet_test_guard: the suite touched live tree state - " + "; ".join(parts)
            + ". Point the test at tmp_path.")


def load_factor(gate=None):
    """Live suite-gate slot holders now, clamped to 1..MAX_SLOTS (v16)."""
    try:
        gate = gate or _gate()
        n = len(gate.held(gate.gate_dir()))
        return max(1, min(int(gate.MAX_SLOTS), n))
    except Exception:  # noqa: BLE001 - a budget helper never breaks a test
        return 1


def budget(seconds, gate=None):
    """A time budget scaled by load_factor() (v16, opt-in)."""
    return float(seconds) * load_factor(gate)


def _gate():
    import importlib.util
    import sys
    key = "fleet_kit_fleet_suite_gate"
    if key in sys.modules:
        return sys.modules[key]
    spec = importlib.util.spec_from_file_location(
        key, Path(__file__).with_name("fleet_suite_gate.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[key] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(key, None)
        raise
    return mod


# = fleet_headless.TEST_ROUTE_ENV (not imported: the guard never loads the kit).
ROUTE_ENV = "FLEET_TEST_HEADLESS_ROUTE"


def _off():
    return (os.environ.get("FLEET_TEST_GUARD") or "").strip().lower() == "off"


def install(ns, root, watch=WATCH, env_roots=None, ignore=IGNORE, inflow=INFLOW,
            extra_ignore=()):
    """Add the autouse fixtures (live-state guard, runtime roots, v19.1 headless
    route) to a conftest's globals()."""
    root = Path(root)
    # v16: progress rows written by a suite carry no owner pid (the session's
    # own claude process would otherwise be recorded); a test that needs one
    # passes owner= or sets FLEET_PROGRESS_OWNER itself.
    os.environ["FLEET_PROGRESS_OWNER"] = "none"
    ignore = tuple(ignore) + tuple(extra_ignore or ())
    roots = dict(env_roots or {})

    @pytest.fixture(scope="session", autouse=True)
    def _fleet_live_state_guard():
        if _off():
            yield
            return
        before = snapshot(root, watch, ignore)
        yield
        msg = verdict(*compare(before, snapshot(root, watch, ignore), inflow))
        if msg:
            pytest.fail(msg, pytrace=False)

    @pytest.fixture(autouse=True)
    def _fleet_headless_route(request):
        """v19.1: fleet_headless reads ~/.fleet/headless_route.json; a test never
        reads or writes the real one. A valid split route in tmp per test, named
        by the env redirect fleet_headless honours only inside a pytest test, so
        the kit is covered under ANY module name (fleet_headless_flash,
        ops.fleet_kit.fleet_headless, ...), loaded before or during the test.
        A test of the route itself monkeypatches route_path or the env again."""
        tmp = request.getfixturevalue("tmp_path_factory").mktemp("fleet-route")
        p = tmp / "headless_route.json"
        p.write_text('{"mode": "split", "version": 1}\n', encoding="ascii", newline="\n")
        mp = pytest.MonkeyPatch()  # v21: private, never the test's shared one
        mp.setenv(ROUTE_ENV, str(p))
        try:
            yield
        finally:
            mp.undo()

    @pytest.fixture(autouse=True)
    def _fleet_runtime_roots(request):
        if not roots or _off():
            yield
            return
        tmp = request.getfixturevalue("tmp_path")  # v21: tmp_path first
        mp = pytest.MonkeyPatch()  # private; undone before tmp_path's teardown
        for var, sub in roots.items():
            mp.setenv(var, str(Path(tmp) / sub))
        try:
            yield
        finally:
            mp.undo()

    ns["_fleet_live_state_guard"] = _fleet_live_state_guard
    ns["_fleet_runtime_roots"] = _fleet_runtime_roots
    ns["_fleet_headless_route"] = _fleet_headless_route
    return ns
