# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 the operator - the kit's owner and sole copyright holder. See NOTICE.
"""Fleet kit v14 - RACE GUARDS: the test-isolation guard (FLEET-COMMON 16).

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
    requests tmp_path and monkeypatch for EVERY test, so both are in every
    test's fixture closure: `"tmp_path" in request.fixturenames` is always
    True. A test or fixture that branches on request.fixturenames must not
    use tmp_path / monkeypatch as its signal.
env FLEET_TEST_GUARD=off disables both (never in a gate run).
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
          "*.lock", "ops/loop/control/headless_budget.json")
SHOW = 5


def snapshot(root, watch=WATCH, ignore=IGNORE):
    """{relpath: (size, mtime_ns)} for every watched, non-ignored file."""
    root = Path(root)
    out = {}
    for w in watch:
        base = root / w
        if not base.is_dir():
            continue
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                p = Path(dirpath) / name
                rel = p.relative_to(root).as_posix()
                if any(fnmatch.fnmatchcase(rel.lower(), g.lower()) for g in ignore):
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


def _off():
    return (os.environ.get("FLEET_TEST_GUARD") or "").strip().lower() == "off"


def install(ns, root, watch=WATCH, env_roots=None, ignore=IGNORE, inflow=INFLOW,
            extra_ignore=()):
    """Add the two autouse fixtures to a conftest's globals()."""
    root = Path(root)
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
    def _fleet_runtime_roots(request):
        if not roots or _off():
            yield
            return
        tmp = request.getfixturevalue("tmp_path")
        mp = request.getfixturevalue("monkeypatch")
        for var, sub in roots.items():
            mp.setenv(var, str(Path(tmp) / sub))
        yield

    ns["_fleet_live_state_guard"] = _fleet_live_state_guard
    ns["_fleet_runtime_roots"] = _fleet_runtime_roots
    return ns
