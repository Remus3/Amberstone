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

Either fires ONLY inside a SANCTIONED implementation, listed in
tests/guard_data/atomic_write/sanctioned_*.py with the reason it may not
import core.polled_json. Everything else routes through
core.polled_json.atomic_write_json / _text / _bytes. A row is keyed on the
enclosing function, never a line number: its bare name, or its dotted
qualname (`HostLog.write`) when the bare name is too generic to key a file on.
There is no directory or package sanction on purpose - it would let every new
writer in that tree start bare, the RM-258 failure itself.

SCOPE: every tracked .py via tests/_repo_walk (ADR-015) EXCEPT
`tests/`, `docs/`, `oss/` (the extracted package IS
an implementation and is drift-pinned to core/polled_json by
tests/test_oss_win32_atomic_io_drift.py) and `ops/fleet_kit/` (vendored
byte-for-byte; a local edit fails its MANIFEST). tools/ is in scope except
the row's own `tools/*extract*` allowlist, tools/tests/ and the named
`_TOOLS_UNCLASSIFIED` baseline, which only shrinks. The two separate-process
agents under tools/ that RM-258 names are long-running ONLOGON tasks, not
generators, and they and the tools/ watchers converted since stay pinned in
`_RUNTIME_TOOLS`. lib/ is wholly in scope: it is not a generator tree - the
in-process app and the LCU post-game collector import
lib/rewind_live_writer.py at runtime - and its s144 baseline of library
writers shrank to empty and was removed. So is ops/audit/: its s144 baseline
of one-shot audit scripts shrank to empty and was removed (the `Share/` mirror
was removed 2026-09-07 and its prefix dropped).
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import pytest

from tests._repo_walk import (REPO_ROOT, iter_repo_files, relative_posix,
                              self_check, tracked_relpaths)
from tests.guard_data import atomic_write

# Every allowlist lives in one area file per path prefix, so lanes edit
# separate files (MAIN ORDER item RC-2); a missing or empty area fails at
# collection: tests/guard_data/atomic_write/, pinned by
# tests/test_guard_data_split_rc2.py.
_DATA = atomic_write.load()

_EXCLUDED_PREFIXES = _DATA.excluded_prefixes

# Long-running tools/ writers that stay pinned in scope: never an extractor,
# never unclassified. Rows: tests/guard_data/atomic_write/runtime_tools.py.
_RUNTIME_TOOLS = _DATA.runtime_tools

# RM-258 residual (s144): tools/ is IN scope by default. Out of scope are the
# one-shot extractors (`tools/*extract*`), tools/ test code and this baseline,
# which only shrinks: tests/guard_data/atomic_write/tools_unclassified.py.
_TOOLS_UNCLASSIFIED = _DATA.tools_unclassified

# RM-258 residual (s144): ops/audit/ is IN scope too. It was exempted wholesale
# as the row's "one-shot generator tree"; its 11 offending audit scripts were
# each converted onto core.polled_json (RM-1713..RM-1716) and the emptied
# baseline was removed rather than kept as a switch a new writer could be
# parked behind; test_every_ops_audit_module_is_in_scope pins its absence.

# RM-258 residual (s144): lib/ was exempted wholesale as a "one-shot generator
# tree", but app/_game_lifecycle.py and lcu/lcu_postgame_collector.py import
# lib/rewind_live_writer.py in-process, so a new lib/ writer started bare. lib/
# is IN scope now; measured 2026-10-30, 6 lib/ modules offended (6 renames + 5
# scratch names) and the runtime one, lib/rewind_live_writer.py, was converted
# onto core.polled_json in the same slice. The entries below are the library
# writers behind the fetch / build pipelines and the two site scrapers, a
# `_LIB_UNCLASSIFIED` baseline that only shrank. Every entry left in s144 by
# converting onto core.polled_json: lib/scrapers/_base.py
# (tests/test_scrapers_atomic_write_rm258.py), lib/icons/downloader.py and
# lib/game_data/fetch.py (tests/test_lib_byte_writers_atomic_write_rm258.py),
# lib/game_data/build.py (tests/test_lib_game_data_build_writer_rm258.py) and
# last lib/ddragon/fetch.py (tests/test_ddragon_fetch_writer_emits_lf.py). The
# empty baseline was removed rather than kept as a switch a new writer could
# be parked behind; test_every_lib_module_is_in_scope pins its absence.


def _is_tools_extractor(rel: str) -> bool:
    return rel.startswith("tools/") and "extract" in rel.rsplit("/", 1)[-1]

# (relpath, enclosing function or its dotted qualname) -> why this
# implementation may not import core.polled_json. Each must itself use a
# per-writer scratch name, a bounded WinError 5 retry and fsync (asserted for
# the ops trio in tests/test_ops_atomic_writers_rm261.py and for the launcher
# below). Rows live in tests/guard_data/atomic_write/sanctioned_*.py.
SANCTIONED = _DATA.sanctioned

_PER_WRITER_HINTS = ("getpid", "token", "uuid", "pid")


def _in_scope(rel: str) -> bool:
    if rel in _RUNTIME_TOOLS:
        return True
    if rel.startswith("tools/"):
        return not (rel.startswith("tools/tests/") or _is_tools_extractor(rel)
                    or rel in _TOOLS_UNCLASSIFIED)
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
                   "ops/rc_supervisor.py", "core/polled_json.py",
                   "lib/rewind_live_writer.py"):
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


def _launcher_writer(module: str):
    """(module, its atomic JSON writer) for each sanctioned launcher writer."""
    import importlib
    mod = importlib.import_module(f"ops.launcher.{module}")
    write = {"service_host": "atomic_write_json", "updater": "_write_json"}[module]
    return mod, getattr(mod, write)


def test_every_launcher_rename_row_has_a_contract_case():
    """A new ops/launcher _replace_with_retry row must join the contract test
    below, or the sanction rests on its reason string alone."""
    rows = {rel for rel, fn in SANCTIONED
            if rel.startswith("ops/launcher/") and fn == "_replace_with_retry"}
    assert rows == {f"ops/launcher/{m}.py" for m in _LAUNCHER_WRITERS}


_LAUNCHER_WRITERS = ("service_host", "updater")


@pytest.mark.parametrize("module", _LAUNCHER_WRITERS)
def test_launcher_writer_meets_the_sanction_contract(tmp_path, monkeypatch, module):
    """The ops/launcher rows are sanctioned on the three requirements, so
    they are asserted on the code, not on the reason string: a per-writer
    scratch name, fsync before the rename, a bounded WinError 5 retry and no
    scratch left behind when the rename fails for good."""
    sh, write = _launcher_writer(module)

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
    write(dest, {"n": 1})
    write(dest, {"n": 2})
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
    write(dest, {"n": 3})
    assert json.loads(dest.read_text(encoding="ascii")) == {"n": 3}

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(sh.os, "replace", refused)
    with pytest.raises(PermissionError):
        write(dest, {"n": 4})
    assert 1 < calls[0] <= 20, calls[0]
    assert [p.name for p in tmp_path.iterdir()] == ["launcher_status.json"]
    assert json.loads(dest.read_text(encoding="ascii")) == {"n": 3}


def _load_phase_watcher():
    """tools/phase_watcher.py under a private name (it is a script, not a
    package module, and its deployed copy has no repo above it)."""
    import importlib.util
    import sys
    alias = "_phase_watcher_rm258"
    spec = importlib.util.spec_from_file_location(
        alias, REPO_ROOT / "tools" / "phase_watcher.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[alias] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(alias, None)
    return mod


def test_phase_watcher_writer_meets_the_sanction_contract(tmp_path, monkeypatch):
    """tools/phase_watcher.py is served to a standalone agent directory with
    no repo above it (tools/phase_watcher_install.ps1), so it cannot import core.polled_json (the RM-752 pin in
    tests/test_tls_floor_rm752.py); its sidecar writer is sanctioned on the
    three requirements instead, asserted here on the code: a per-writer
    scratch name, fsync before the rename, a bounded WinError 5 retry, the
    scratch removed when the rename fails for good - and LF bytes on disk."""
    pw = _load_phase_watcher()
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

    monkeypatch.setattr(pw.os, "replace", rec_replace)
    monkeypatch.setattr(pw.os, "fsync", rec_fsync)
    monkeypatch.setattr(pw.time, "sleep", lambda _s: None)
    meta = {"topic": "gameflow_phase", "sub_phase": "ChampSelect",
            "queue_id": 420, "captured_at": "2026-05-27T21:15:00Z"}
    dest = pw.write_sidecar(tmp_path, meta, [{"monitor": "game"}])
    assert pw.write_sidecar(tmp_path, meta, [{"monitor": "game"}]) == dest
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith(dest.name + ".") and name.endswith(".tmp")
        assert f".{os.getpid()}." in name, name
    raw = dest.read_bytes()
    assert b"\r\n" not in raw and b"\n" in raw
    assert json.loads(raw)["frames"] == [{"monitor": "game"}]

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(pw.os, "replace", flaky)
    pw.write_sidecar(tmp_path, dict(meta, queue_id=450), [])
    assert json.loads((tmp_path / dest.name.replace("_420_", "_450_"))
                      .read_bytes())["queue_id"] == 450

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(pw.os, "replace", refused)
    with pytest.raises(PermissionError):
        pw.write_sidecar(tmp_path, dict(meta, queue_id=1700), [])
    assert 1 < calls[0] <= 20, calls[0]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [dest.name, dest.name.replace("_420_", "_450_")])


def test_moon_sync_poller_writer_meets_the_sanction_contract(tmp_path, monkeypatch):
    """tools/moon_sync_poller.py keeps core/ off its import path on purpose,
    so its one writer (status.md, findings.json, poller_seen.json and the
    --ping stamp all go through _atomic_write) is sanctioned on the three
    requirements, asserted here on the code: a per-writer scratch name, fsync
    before the rename, a bounded WinError 5 retry, the scratch removed when
    the rename fails for good - and LF bytes on disk."""
    from tools import moon_sync_poller as msp
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

    monkeypatch.setattr(msp.os, "replace", rec_replace)
    monkeypatch.setattr(msp.os, "fsync", rec_fsync)
    monkeypatch.setattr(msp.time, "sleep", lambda _s: None)
    dest = tmp_path / "status.md"
    msp._atomic_write(dest, "# a\n- b\n")
    msp._atomic_write(dest, "# a\n- c\n")
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith("status.md.") and name.endswith(".tmp"), name
        assert f".{os.getpid()}." in name, name
    assert dest.read_bytes() == b"# a\n- c\n"

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(msp.os, "replace", flaky)
    msp._atomic_write(dest, "# a\n- d\n")
    assert dest.read_bytes() == b"# a\n- d\n"

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(msp.os, "replace", refused)
    with pytest.raises(PermissionError):
        msp._atomic_write(dest, "# a\n- e\n")
    assert 1 < calls[0] <= 20, calls[0]
    assert [p.name for p in tmp_path.iterdir()] == ["status.md"]
    assert dest.read_bytes() == b"# a\n- d\n"


def test_stop_claim_gate_writer_meets_the_sanction_contract(tmp_path, monkeypatch):
    """tools/stop_claim_gate.py is a portable stdlib-only Stop hook, so its
    one writer (the report, the history roll and the seen set all go through
    _atomic_write) is sanctioned on the three requirements, asserted here on
    the code: a per-writer scratch name, fsync before the rename, a bounded
    WinError 5 retry, the scratch removed when the rename fails for good -
    and LF bytes on disk. The three callers keep their failure contracts:
    write_report raises (RM-796 reports it), the history and the seen set
    swallow (bookkeeping never breaks the gate)."""
    from tools import stop_claim_gate as gate
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

    monkeypatch.setattr(gate.os, "replace", rec_replace)
    monkeypatch.setattr(gate.os, "fsync", rec_fsync)
    monkeypatch.setattr(gate.time, "sleep", lambda _s: None)
    dest = tmp_path / "stop_claim_gate_last.json"
    gate.write_report({"n": 1}, dest)
    gate.write_report({"n": 2}, dest)
    assert events == ["fsync", "replace", "fsync", "replace"]
    assert scratch[0] != scratch[1], scratch
    for name in scratch:
        assert name.startswith(dest.name + ".") and name.endswith(".tmp"), name
        assert f".{os.getpid()}." in name, name
    raw = dest.read_bytes()
    assert b"\r\n" not in raw and b"\n" in raw
    assert json.loads(raw) == {"n": 2}

    history = tmp_path / "history.jsonl"
    for i in range(4):
        gate.append_history({"session_id": f"s{i}"}, history, cap=2)
    rows = history.read_bytes().split(b"\n")
    assert b"\r" not in history.read_bytes()
    assert [json.loads(r)["session_id"] for r in rows if r] == ["s2", "s3"]

    refusals = [3]

    def flaky(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(gate.os, "replace", flaky)
    gate.write_report({"n": 3}, dest)
    assert json.loads(dest.read_bytes()) == {"n": 3}

    calls = [0]

    def refused(src, dst):
        calls[0] += 1
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(gate.os, "replace", refused)
    with pytest.raises(PermissionError):
        gate.write_report({"n": 4}, dest)
    assert 1 < calls[0] <= 20, calls[0]
    gate.append_history({"session_id": "s4"}, history, cap=2)
    seen = tmp_path / "seen" / "s.json"
    gate.save_seen(seen, "s", {"k"})
    assert not seen.exists()
    assert list(seen.parent.iterdir()) == []
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        [dest.name, history.name, "seen"])
    assert json.loads(dest.read_bytes()) == {"n": 3}


def test_shadow_archive_split_swap_meets_the_sanction_contract(tmp_path,
                                                               monkeypatch):
    """tools/shadow_archive_split.py swaps two files (archive + live) and
    keeps core.polled_json out of the swap on purpose (SANCTIONED row): a
    retry inside one rename call would land a stale kept snapshot over a row
    appended meanwhile. Asserted on the code: a per-writer scratch name,
    fsync before every rename, a refused live rename rolled back and retried
    a level up with the append merged, the retry bounded, and no scratch
    left when it fails for good."""
    from tools import shadow_archive_split as sas
    real_replace, real_fsync = os.replace, os.fsync
    leak = b'{"ts": "2026-07-01T00:00:00", "enemy_comp": []}\n'
    real_row = (b'{"ts": "2026-07-01T00:00:01", '
                b'"enemy_comp": ["Ahri", "Ashe", "Garen", "Lux", "Zed"]}\n')
    late_row = real_row.replace(b"00:00:01", b"00:00:02")

    def corpus(d):
        live = d / "x_shadow.jsonl"
        live.parent.mkdir(parents=True, exist_ok=True)
        live.write_bytes(real_row + leak + real_row)
        return live, d / "x_rm859_test_leak_shadow.jsonl"

    events: list[str] = []
    scratch: list[str] = []

    def rec_replace(src, dst):
        events.append("replace")
        scratch.append(Path(src).name)
        return real_replace(src, dst)

    def rec_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    monkeypatch.setattr(sas.os, "replace", rec_replace)
    monkeypatch.setattr(sas.os, "fsync", rec_fsync)
    monkeypatch.setattr(sas.time, "sleep", lambda _s: None)
    idle = lambda: False  # noqa: E731
    live, archive = corpus(tmp_path / "a")
    sas.archive_split(live, archive, game_live=idle)
    assert events == ["fsync", "fsync", "replace", "replace"], events
    names = list(scratch)
    live2, archive2 = corpus(tmp_path / "b")
    sas.archive_split(live2, archive2, game_live=idle)
    names += scratch[2:]
    assert len(set(names)) == 4, names
    for name in names:
        assert name.endswith(".tmp") and ".split." in name, name
        assert f".{os.getpid()}." in name, name

    # A refused live rename: the archive goes back, the round re-reads the
    # live file, merges the row appended meanwhile, and the retry lands it.
    live3, archive3 = corpus(tmp_path / "c")
    refusals = [1]

    def flaky(src, dst):
        if os.fspath(dst) == os.fspath(live3) and refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    def writer_appends(round_no):
        if round_no == 1:
            with open(live3, "ab") as fh:
                fh.write(late_row)

    monkeypatch.setattr(sas.os, "replace", flaky)
    report = sas.archive_split(live3, archive3, game_live=idle,
                               _before_replace=writer_appends)
    assert report["verified"] and report["tail_rows_merged"] == 1, report
    assert live3.read_bytes() == real_row + real_row + late_row
    assert archive3.read_bytes() == leak

    live4, archive4 = corpus(tmp_path / "d")
    original = live4.read_bytes()
    calls = [0]

    def refused(src, dst):
        if os.fspath(dst) == os.fspath(live4):
            calls[0] += 1
            raise PermissionError(13, "Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(sas.os, "replace", refused)
    with pytest.raises(sas.SplitAborted) as exc:
        sas.archive_split(live4, archive4, game_live=idle, max_rounds=3)
    assert exc.value.reason == "replace_failed"
    assert calls[0] == 3
    assert live4.read_bytes() == original
    assert sorted(p.name for p in live4.parent.iterdir()) == [live4.name]


def test_scope_keeps_runtime_tools_and_drops_generators():
    assert _in_scope("tools/lcu_agent.py")
    assert _in_scope("tools/hotkey_listener.py")
    assert _in_scope("tools/cost_health_watchdog.py")
    assert _in_scope("tools/ci_watchdog.py")
    assert _in_scope("tools/progress_watch.py")
    assert _in_scope("tools/spec_watch.py")
    assert _in_scope("tools/ds_feed_watch.py")
    assert _in_scope("tools/session_checklist.py")
    assert _in_scope("tools/inbox_responder.py")
    assert _in_scope("tools/rc_facts.py")
    assert _in_scope("tools/inbox_responder_runner.py")
    assert _in_scope("tools/phase_watcher.py")
    assert _in_scope("tools/moon_sync_poller.py")
    assert _in_scope("tools/upstream_drift_check.py")
    assert _in_scope("tools/stop_claim_gate.py")
    assert _in_scope("tools/rofl_dedupe.py")
    assert _in_scope("tools/timeline_ingest.py")
    assert _in_scope("tools/replay_roster_pull.py")
    assert _in_scope("tools/ladder_role_scout.py")
    assert not _in_scope("tools/daemon_slayer_extract.py")
    assert not _in_scope("ops/fleet_kit/fleet_headless.py")
    assert _in_scope("coach_integration/_coach.py")


def test_a_new_tools_writer_starts_in_scope():
    """The RM-258 residual: a tools/ module is guarded unless it is an
    extractor, tools/ test code or a named unclassified entry - a new writer
    no longer starts bare under a directory-wide exemption."""
    assert _in_scope("tools/a_new_polled_writer.py")
    assert _in_scope("tools/ds_cross_eval/a_new_writer.py")
    assert not _in_scope("tools/daemon_slayer_cdragon_ratio_extract.py")
    assert not _in_scope("tools/tests/test_cdragon_ratio_extract.py")
    assert not _in_scope("tools/build_portable.py")


def test_tools_baseline_is_exact():
    """Every unclassified entry is a tracked tools/ module that still
    offends, is not an extractor and is not a converted watcher - so a
    conversion has to shrink the set, and the set never hides a clean file."""
    tracked = {relative_posix(p) for p in iter_repo_files(REPO_ROOT, ("*.py",))}
    assert not _TOOLS_UNCLASSIFIED & _RUNTIME_TOOLS
    stale = []
    for rel in sorted(_TOOLS_UNCLASSIFIED):
        assert rel in tracked, f"unclassified entry {rel} is not tracked"
        assert not _is_tools_extractor(rel), rel
        renames, scratch = scan([(rel, REPO_ROOT / rel)])
        if not renames and not scratch:
            stale.append(rel)
    assert stale == [], (
        "these no longer hand-roll an atomic write - drop them from "
        "_TOOLS_UNCLASSIFIED (add a long-running one to _RUNTIME_TOOLS):\n  "
        + "\n  ".join(stale))


def test_a_new_lib_writer_starts_in_scope():
    """lib/ is no longer a directory-wide exemption: the runtime writer, every
    converted library writer and any new lib/ module are guarded."""
    assert _in_scope("lib/rewind_live_writer.py")
    assert _in_scope("lib/ingest_receipt.py")
    assert _in_scope("lib/a_new_polled_writer.py")
    assert _in_scope("lib/scrapers/_base.py")
    assert _in_scope("lib/icons/downloader.py")
    assert _in_scope("lib/game_data/fetch.py")
    assert _in_scope("lib/game_data/build.py")
    assert _in_scope("lib/ddragon/fetch.py")
    assert _in_scope("scripts/rewind_scraper.py")


def test_every_lib_module_is_in_scope():
    """The lib/ baseline emptied in s144 and was removed: every tracked lib/
    module is scanned, so no lib/ writer can be parked outside the guard.
    Anchored on the last converted writer so an empty walk cannot pass."""
    lib_files = [rel for rel in (relative_posix(p) for p in
                 iter_repo_files(REPO_ROOT, ("*.py",)))
                 if rel.startswith("lib/")]
    assert "lib/ddragon/fetch.py" in lib_files
    scanned = {rel for rel, _ in _runtime_files()}
    assert sorted(set(lib_files) - scanned) == []
    assert "_LIB_UNCLASSIFIED" not in globals()


def test_every_excluded_prefix_still_matches_a_tracked_file():
    """An excluded prefix is a tree the guard never scans. One that matches no
    tracked file is a dead row: a tree of that name added later would start
    exempt (the retired `Share/` mirror was one - removed 2026-09-07,
    86f124a6f, yet its prefix stayed in the list). Anchored on the real index
    so an empty listing cannot pass."""
    tracked = tracked_relpaths()
    assert tracked, "git index unavailable"
    assert "core/polled_json.py" in tracked
    dead = [p for p in _EXCLUDED_PREFIXES
            if not any(t.startswith(p) for t in tracked)]
    assert dead == [], f"excluded prefixes with no tracked file: {dead}"


def test_a_new_ops_audit_writer_starts_in_scope():
    """ops/audit/ is no longer a directory-wide exemption and has no baseline:
    every audit script, the three ds_perm_swarm runners included, and any new
    one is guarded."""
    assert _in_scope("ops/audit/a_new_audit_writer.py")
    assert _in_scope("ops/audit/ds_cross_eval/a_new_writer.py")
    assert _in_scope("ops/audit/ds_perm_swarm/a_new_swarm_writer.py")
    assert _in_scope("ops/audit/ds_perm_swarm/run_harness.py")
    assert "ops/audit/" not in _EXCLUDED_PREFIXES


def test_every_ops_audit_module_is_in_scope():
    """The ops/audit baseline emptied in s144 and was removed: every tracked
    ops/audit module is scanned and none offends, so no audit writer can be
    parked outside the guard. Anchored on the last converted runner so an
    empty walk cannot pass."""
    audit_files = [rel for rel in (relative_posix(p) for p in
                   iter_repo_files(REPO_ROOT, ("*.py",)))
                   if rel.startswith("ops/audit/")]
    assert "ops/audit/ds_perm_swarm/run_harness.py" in audit_files
    scanned = {rel for rel, _ in _runtime_files()}
    assert sorted(set(audit_files) - scanned) == []
    renames, scratch = scan([(rel, REPO_ROOT / rel) for rel in audit_files])
    assert renames == [] and scratch == []
    assert "_AUDIT_UNCLASSIFIED" not in globals()
