"""RM-258 + RM-261 - no runtime module may hand-roll an atomic write.

RM-258: roughly 45 runtime writers finished a tmp+rename with a BARE replace
(no WinError 5 retry), and the repo carried three separate hardened
implementations with nothing forcing a writer onto one of them - so every new
polled writer started bare by default. RM-261: ~96 modules built their scratch
file from the DESTINATION alone (`<dest>.tmp`), the shared-scratch collision
RM-254 fixed inside core/polled_json.

The two rows are the same population of writers, so one guard covers both
spellings of the rename and every destination-derived scratch name:

  Rule R (rename):  `os.replace(a, b)` and the one-positional-argument
                    `x.replace(y)` (Path.replace - the spelling CLAUDE.md's
                    own atomic-write rule prescribes, and the one a plain
                    `grep os.replace` misses).
  Rule S (scratch): `.with_suffix(...)` / `.with_name(...)` / `str + ...` /
                    an f-string whose literal tail ends in `.tmp` with no
                    per-writer component (getpid / token / uuid) in it.

Either fires ONLY inside a SANCTIONED implementation, listed below with the
reason it may not import core.polled_json. Everything else routes through
core.polled_json.atomic_write_json / _text / _bytes. A row is keyed on the
enclosing function, never a line number: its bare name, or its dotted
qualname (`HostLog.write`) when the bare name is too generic to key a file on.
There is no directory or package sanction on purpose - it would let every new
writer in that tree start bare, the RM-258 failure itself.

SCOPE: every tracked .py via tests/_repo_walk (ADR-015) EXCEPT the one-shot
generator trees the rows themselves allowlist (`tools/`, `scripts/`,
`ops/audit/`, `Share/`, `lib/`), plus `tests/`, `docs/`, `oss/` (the extracted
package IS an implementation and is drift-pinned to core/polled_json by
tests/test_oss_win32_atomic_io_drift.py) and `ops/fleet_kit/` (vendored
byte-for-byte; a local edit fails its MANIFEST). The two separate-process
agents under tools/ that RM-258 names ARE in scope - they are long-running
ONLOGON tasks, not generators.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, iter_repo_files, relative_posix, self_check

_EXCLUDED_PREFIXES = (
    "tests/",
    "docs/",
    "oss/",
    "tools/",
    "scripts/",
    "ops/audit/",
    "ops/fleet_kit/",
    "Share/",
    "lib/",
)

# Long-running separate-process agents that live under tools/ (RM-258 names
# both). In scope despite the tools/ exclusion.
_RUNTIME_TOOLS = frozenset({
    "tools/lcu_agent.py",
    "tools/hotkey_listener.py",
})

# (relpath, enclosing function or its dotted qualname) -> why this
# implementation may not import core.polled_json. Each must itself use a
# per-writer scratch name, a bounded WinError 5 retry and fsync (asserted for
# the ops trio in tests/test_ops_atomic_writers_rm261.py and for the launcher
# below).
SANCTIONED = {
    ("core/polled_json.py", "_replace_with_retry"):
        "the canonical implementation every other writer routes through",
    ("ops/rc_supervisor.py", "_replace_with_retry"):
        "FROZEN watchdog: stdlib-only by design so a broken app package "
        "cannot take the process that restarts it down with it",
    ("ops/rc_dev_runtime.py", "_atomic_write_json"):
        "FROZEN runtime host: stdlib-only heartbeat writer with its own "
        "measured retry budget (tests/test_rc_dev_runtime_atomic_write_retry.py)",
    ("ops/rc_transactional_deploy.py", "_replace_with_retry"):
        "deploy transaction runs while the app tree is being swapped, so it "
        "must not import from the tree it is replacing",
    ("core/log_rotation.py", "try_rotate"):
        "log ROTATION, not an atomic write (RM-718 a), checked against the "
        "three requirements above. Per-writer scratch: yes - "
        "<name>.rotating/.dropping.<pid>.<token>, and orphans from a crash are "
        "recovered, never overwritten. WinError 5 retry: deliberately none in "
        "the call - the refusal here is not a reader's millisecond poll but "
        "another process holding the log open for its lifetime (measured "
        "2026-10-25 as WinError 32, a sharing violation, RM-864 c), so an "
        "in-call retry only stalls the logging call that triggered the "
        "rollover; the bounded retry is one level up (the handler re-attempts "
        "after _RETRY_AFTER_S, the one-shot writer on its next run), and a "
        "refusal rolls the applied renames back, best effort and no-clobber (a "
        "refused roll-back rename leaves its file one slot higher or under a "
        "scratch name recover_orphans() preserves). fsync: nothing to "
        "flush - it only renames existing files, it writes no payload. It "
        "may not use core.polled_json because those helpers write a payload "
        "to a destination; there is no payload here",
    ("ops/launcher/service_host.py", "_replace_with_retry"):
        "PKG-1 launcher service host: stdlib-only and run under `python -I` "
        "with no RC module on sys.path, because it starts and stops the "
        "backend core.polled_json belongs to (docs/PACKAGING_PLAN.md 3.1). "
        "Its atomic_write_json meets the three requirements, asserted by "
        "test_launcher_writer_meets_the_sanction_contract below: a "
        "<dest>.<pid>.<token>.tmp scratch, flush + fsync before the rename, "
        "a bounded PermissionError (WinError 5) retry, and the scratch "
        "removed when the rename fails for good",
    ("ops/launcher/service_host.py", "HostLog.write"):
        "log ROTATION, not an atomic write (the core/log_rotation.py "
        "try_rotate class), in the same stdlib-only launcher, checked against "
        "the three requirements. fsync: nothing to flush - the rename moves "
        "an existing file and writes no payload. WinError 5 retry: none in "
        "the call - a refused rename (a reader holding the log or its `.1` "
        "open) is swallowed, the line still appended, and the next write "
        "re-checks the size and re-attempts, so the retry is one level up "
        "and the log outgrows LOG_MAX_BYTES only while that holder stays. "
        "Per-writer scratch: none - the target is the fixed `.1` slot. The "
        "host is single-writer under HostLock except main()'s two pre-lock "
        "lines (bad manifest, lock refused), so a second launch crossing the "
        "size threshold in the same instant as the live host can replace "
        "`.1` with a one-line file: one lost older generation, never torn "
        "bytes (residual reported for the PKG-1b slice)",
}

_PER_WRITER_HINTS = ("getpid", "token", "uuid", "pid")


def _in_scope(rel: str) -> bool:
    if rel in _RUNTIME_TOOLS:
        return True
    return not rel.startswith(_EXCLUDED_PREFIXES)


def _runtime_files() -> list[tuple[str, Path]]:
    out = []
    for p in iter_repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(p)
        if _in_scope(rel):
            out.append((rel, p))
    return out


def _enclosing_functions(tree: ast.AST) -> dict[int, tuple[str, str]]:
    """node id -> (innermost enclosing function name, its dotted qualname).

    The qualname joins every enclosing class and function (`HostLog.write`),
    so a SANCTIONED row can name one method without exempting every
    same-named function in the file."""
    owner: dict[int, tuple[str, str]] = {}

    def visit(node: ast.AST, fn: str, qual: str, scope: str) -> None:
        for child in ast.iter_child_nodes(node):
            name, q, inner = fn, qual, scope
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = child.name
                q = scope + child.name
                inner = q + "."
            elif isinstance(child, ast.ClassDef):
                inner = scope + child.name + "."
            owner[id(child)] = (name, q)
            visit(child, name, q, inner)

    visit(tree, "<module>", "<module>", "")
    return owner


def _str_tail(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr) and node.values:
        last = node.values[-1]
        if isinstance(last, ast.Constant) and isinstance(last.value, str):
            return last.value
    return None


def _mentions_per_writer(node: ast.AST, src: str) -> bool:
    seg = (ast.get_source_segment(src, node) or "").lower()
    return any(h in seg for h in _PER_WRITER_HINTS)


def _is_rename(node: ast.Call) -> bool:
    f = node.func
    if not isinstance(f, ast.Attribute) or f.attr != "replace":
        return False
    if isinstance(f.value, ast.Name) and f.value.id == "os":
        return True
    # Path.replace(target): exactly one positional arg, no keywords. str.replace
    # always takes two, datetime.replace is keyword-only in practice.
    return (len(node.args) == 1 and not node.keywords
            and not isinstance(f.value, ast.Constant))


def _is_dest_derived_scratch(node: ast.AST, src: str) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr in ("with_suffix", "with_name") and node.args:
        tail = _str_tail(node.args[0])
        if tail is None and isinstance(node.args[0], ast.BinOp):
            tail = _str_tail(node.args[0].right)
        return bool(tail and tail.endswith(".tmp")) and not _mentions_per_writer(node, src)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        tail = _str_tail(node.right)
        return bool(tail and tail.endswith(".tmp")) and not _mentions_per_writer(node, src)
    if isinstance(node, ast.JoinedStr):
        tail = _str_tail(node)
        return bool(tail and tail.endswith(".tmp")) and not _mentions_per_writer(node, src)
    return False


def scan(files=None, sanctioned=None) -> tuple[list[str], list[str]]:
    """Return (rename offenders, scratch-name offenders) as 'path:line fn'."""
    sanctioned = SANCTIONED if sanctioned is None else sanctioned
    renames: list[str] = []
    scratch: list[str] = []
    for rel, path in (files if files is not None else _runtime_files()):
        src = path.read_bytes().decode("utf-8")
        tree = ast.parse(src)
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            fn, qual = owner.get(id(node), ("<module>", "<module>"))
            if (rel, fn) in sanctioned or (rel, qual) in sanctioned:
                continue
            if isinstance(node, ast.Call) and _is_rename(node):
                renames.append(f"{rel}:{node.lineno} {fn}")
            elif _is_dest_derived_scratch(node, src):
                scratch.append(f"{rel}:{getattr(node, 'lineno', 0)} {fn}")
    # A with_suffix(x + ".tmp") matches as the call AND as its BinOp argument;
    # report each site once.
    return sorted(set(renames)), sorted(set(scratch))


@pytest.fixture(scope="module")
def offenders():
    self_check()
    files = _runtime_files()
    # Empty is never clean: the scope must still reach the writers this guard
    # exists for.
    rels = {r for r, _ in files}
    for anchor in ("coach_integration/_coach.py", "tools/lcu_agent.py",
                   "ops/rc_supervisor.py", "core/polled_json.py"):
        assert anchor in rels, f"guard scope lost {anchor}"
    return scan(files)


def test_rm258_no_runtime_module_hand_rolls_the_rename(offenders):
    renames, _ = offenders
    assert renames == [], (
        "bare tmp->rename outside a sanctioned implementation - route it "
        "through core.polled_json.atomic_write_json/_text/_bytes:\n  "
        + "\n  ".join(renames)
    )


def test_rm261_no_runtime_module_derives_its_scratch_name_from_the_destination(offenders):
    _, scratch = offenders
    assert scratch == [], (
        "destination-derived scratch name (shared by every writer of that "
        "file) - use core.polled_json, or a per-writer pid+token name:\n  "
        + "\n  ".join(scratch)
    )


def test_every_sanctioned_entry_still_exists():
    """A stale allowlist entry silently widens nothing today but hides a
    rename the day a function of that name reappears; keep it exact."""
    for rel, fn in SANCTIONED:
        tree = ast.parse((REPO_ROOT / rel).read_bytes().decode("utf-8"))
        owner = _enclosing_functions(tree)
        # Each def node owns itself, so this is every function's bare name
        # and dotted qualname.
        names = {v for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 for v in owner[id(n)]}
        assert fn in names, f"SANCTIONED entry {rel}:{fn} no longer exists"


@pytest.mark.parametrize("snippet, rename, scratch", [
    ("import os\ndef f(t, p):\n    os.replace(t, p)\n", 1, 0),
    ("def f(t, p):\n    t.replace(p)\n", 1, 0),
    ("def f(s):\n    return s.replace('a', 'b')\n", 0, 0),
    ("def f(p):\n    return p.with_suffix(p.suffix + '.tmp')\n", 0, 1),
    ("def f(p):\n    return p.with_suffix('.json.tmp')\n", 0, 1),
    ("def f(p):\n    return str(p) + '.tmp'\n", 0, 1),
    ("import os\ndef f(p):\n    return p.with_name(f'{p.name}.{os.getpid()}.tmp')\n", 0, 0),
])
def test_detector_positive_and_negative_controls(tmp_path, snippet, rename, scratch):
    f = tmp_path / "m.py"
    f.write_bytes(snippet.encode())
    r, s = scan([("core/m.py", f)])
    assert (len(r), len(s)) == (rename, scratch), (r, s)


def test_a_qualname_row_exempts_one_method_not_every_same_named_function(tmp_path):
    f = tmp_path / "m.py"
    f.write_bytes(b"import os\n"
                  b"class Log:\n"
                  b"    def write(self, a, b):\n"
                  b"        os.replace(a, b)\n"
                  b"def write(a, b):\n"
                  b"    os.replace(a, b)\n")
    r, _ = scan([("core/m.py", f)], sanctioned={("core/m.py", "Log.write"): "x"})
    assert r == ["core/m.py:6 write"]


def test_launcher_writer_meets_the_sanction_contract(tmp_path, monkeypatch):
    """The ops/launcher rows are sanctioned on the three requirements, so
    they are asserted on the code, not on the reason string: a per-writer
    scratch name, fsync before the rename, a bounded WinError 5 retry and no
    scratch left behind when the rename fails for good."""
    from ops.launcher import service_host as sh

    real_replace, real_fsync = os.replace, os.fsync
    events: list[str] = []
    scratch: list[str] = []

    def rec_replace(src, dst):
        events.append("replace")
        scratch.append(Path(src).name)
        return real_replace(src, dst)

    def rec_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(sh.os, "replace", rec_replace)
    monkeypatch.setattr(sh.os, "fsync", rec_fsync)
    monkeypatch.setattr(sh.time, "sleep", lambda _s: None)
    dest = tmp_path / "launcher_status.json"
    sh.atomic_write_json(dest, {"n": 1})
    sh.atomic_write_json(dest, {"n": 2})
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith("launcher_status.json.") and name.endswith(".tmp")
        assert f".{os.getpid()}." in name, name

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(sh.os, "replace", flaky)
    sh.atomic_write_json(dest, {"n": 3})
    assert json.loads(dest.read_text(encoding="ascii")) == {"n": 3}

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(sh.os, "replace", refused)
    with pytest.raises(PermissionError):
        sh.atomic_write_json(dest, {"n": 4})
    assert 1 < calls[0] <= 20, calls[0]
    assert [p.name for p in tmp_path.iterdir()] == ["launcher_status.json"]
    assert json.loads(dest.read_text(encoding="ascii")) == {"n": 3}


def test_scope_keeps_runtime_tools_and_drops_generators():
    assert _in_scope("tools/lcu_agent.py")
    assert _in_scope("tools/hotkey_listener.py")
    assert not _in_scope("tools/daemon_slayer_extract.py")
    assert not _in_scope("ops/fleet_kit/fleet_headless.py")
    assert _in_scope("coach_integration/_coach.py")
