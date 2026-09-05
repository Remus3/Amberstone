"""tests/test_loop_control_sibling_writers_lane8_cycle48.py - RM-250.

LANE 8 CYCLE 48. Three SIBLING hand-rolled atomic writers carry the WinError 5
exposure that cycle 21 closed in `dashboard/routes_loop_control.py`, and they
write the SAME `ops/loop/control/` files:

  * ops/loop/loop_controller.py  awrite   - writes STOP (:174) and cycle.txt
  * ops/loop/intents.py          _awrite  - rewrites the INTENT file consumed
  * ops/loop/steer.py            _awrite  - writes STEER.cursor

All three did `tmp.write_*` + a BARE `os.replace` with no PermissionError
retry. `STOP` is read from three poll loops - loop_controller.py:772/786 every
5 s, ops/loop/claude_gui_bridge.ahk:299 every 1 s, and
dashboard/routes_loop_status.py:450 `read_text()` on every browser poll of
GET /api/loop-status. On Windows a reader holding the destination open
share-locks it and a bare `os.replace` raises PermissionError (WinError 5), so
the contention is routine rather than theoretical.

THREE defects, not the one RM-250 filed:

  W1 (filed)  bare os.replace, no bounded retry.
  W2 (NEW)    the scratch name is `str(path) + ".tmp"`, derived from the
              DESTINATION alone, so every writer of a given file opens the SAME
              scratch path. STOP has two independent writers - loop_controller
              awrite(:174) and dashboard/routes_loop_control._awrite(:344,:587)
              - so two of them interleave: B truncates and renames the scratch
              while A is still filling it. This is the exact defect cycle 24
              fixed inside core/polled_json via `_scratch_path`; the siblings
              never got it, and RM-250 did not name it.
  W3          loop_controller.awrite used `Path.write_text`, which rewrites LF
              as CRLF on Windows (reference_windows_write_text_crlf_byte_count).
              intents._awrite and steer._awrite already wrote bytes.

PORTABILITY. These tests inject the fault at the `os.replace` boundary via
tests/_replace_faults.py rather than asking the OS for it. Opening a file does
NOT block a rename on POSIX, so an OS-borrowed injector is green on the Windows
box that authors it and either red or VACUOUSLY green on the Linux CI runner -
that is lane 8 cycle 26's finding, and this module is bound by it.

THE sys.path CONSTRAINT, measured this cycle. RM-250's stated acceptance was
"each writer routes through core.polled_json.atomic_write_bytes". Taken
literally as a plain top-level import that is UNSHIPPABLE: loop_controller.py:36
records that the controller "is loaded by absolute file path (launcher +
tests), so ops/loop is never on sys.path", and the repo root is not on it
either - `import core.polled_json` from that context raises
ModuleNotFoundError: No module named 'core' (measured). The writers therefore
resolve the primitive with the absolute-path bind idiom the modules already use
for adjudicator / winmutex / slots, and test_absolute_path_load_still_resolves
below is the guard that keeps that working.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import sys
from pathlib import Path

import pytest

from core.polled_json import _REPLACE_RETRY_DELAYS_S as _DELAYS
from tests._replace_faults import replace_fails

_ROOT = Path(__file__).resolve().parent.parent
_OPS_LOOP = _ROOT / "ops" / "loop"


# --------------------------------------------------------------- module loading
def _load_by_path(stem: str):
    """Load an ops/loop module the way PRODUCTION does - by absolute file path.

    This is the launcher's idiom (ops/loop/lane_launcher.py) and the idiom the
    existing loop_controller tests use. Loading it this way rather than via
    `from ops.loop import ...` is deliberate: it is the context in which the
    repo root is absent from sys.path, which is the whole point of the bind.
    """
    name = f"{stem}_uut_cycle48"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _OPS_LOOP / f"{stem}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def controller():
    return _load_by_path("loop_controller")


@pytest.fixture(scope="module")
def intents():
    return _load_by_path("intents")


@pytest.fixture(scope="module")
def steer():
    return _load_by_path("steer")


# Each writer, paired with a callable that writes `text` through it. steer's
# _awrite takes BYTES while the other two take str - the signatures genuinely
# differ, so the adapter is per-writer rather than one shared call.
def _writers(controller, intents, steer, adjudicator):
    return {
        "loop_controller.awrite": (
            controller, lambda p, t: controller.awrite(p, t)),
        "intents._awrite": (
            intents, lambda p, t: intents._awrite(p, t)),
        "steer._awrite": (
            steer, lambda p, t: steer._awrite(p, t.encode("utf-8"))),
        "adjudicator._atomic_write": (
            adjudicator, lambda p, t: adjudicator._atomic_write(p, t)),
    }


@pytest.fixture(scope="module")
def adjudicator():
    return _load_by_path("adjudicator")


@pytest.fixture
def writers(controller, intents, steer, adjudicator):
    return _writers(controller, intents, steer, adjudicator)


# The four writers with a directly callable (path, text) shape. The other three
# swept this cycle - ops/loop/lanes.py repoint_lane_pid, ops/loop/done_sentinel
# and ops/loop/claude_stub - write from inside larger functions and are covered
# structurally by test_no_ops_loop_module_hand_rolls_an_atomic_write below.
_DIRECT_WRITERS = ["loop_controller.awrite", "intents._awrite",
                   "steer._awrite", "adjudicator._atomic_write"]

# Every ops/loop module swept this cycle. RM-250 named the first three; the
# other four were found by the cycle's own adversarial refutation pass, which
# REFUTED the claim that three was the complete sibling set.
_SWEPT_MODULES = ("loop_controller", "intents", "steer", "adjudicator",
                  "lanes", "done_sentinel", "claude_stub")


def _scratches(dest: Path):
    """Every file in the destination's directory that is not the destination."""
    return sorted(p.name for p in dest.parent.iterdir() if p != dest)


# ------------------------------------------------------ W1: the transient case
@pytest.mark.parametrize(
    "which",
    _DIRECT_WRITERS)
def test_writer_survives_a_transient_share_lock(tmp_path, writers, which):
    """A reader that RELEASES inside the ~275 ms backoff must not lose the write.

    This is the case the retry loop exists for. RM-250 is explicit that a
    reader held for the WHOLE attempt tests the exhaustion path instead and
    "will look like a failing fix", so the injector is bounded with times=2:
    two failures, then the real replace goes through on the third attempt.
    """
    _mod, write = writers[which]
    dest = tmp_path / "STOP"

    with replace_fails(dest, times=2) as rec:
        write(dest, "halted by the operator")

    assert rec.failures == 2, "the injector must have driven the retry loop"
    assert dest.read_bytes() == b"halted by the operator"
    assert _scratches(dest) == [], "a survived retry must strand no scratch file"


# ----------------------------------------------------- W1: the exhaustion case
@pytest.mark.parametrize(
    "which",
    _DIRECT_WRITERS)
def test_writer_exhausts_the_backoff_then_raises_and_strands_nothing(
        tmp_path, writers, which):
    """Permanent contention still fails - but it fails CLEANLY.

    The bounded backoff is a retry, not a hang: an unbounded loop would convert
    a visible error into a wedged thread. After the last delay the
    PermissionError must escape, and the scratch file must not survive it.
    """
    _mod, write = writers[which]
    dest = tmp_path / "STOP"

    with replace_fails(dest) as rec:
        with pytest.raises(PermissionError):
            write(dest, "halted by the operator")

    assert rec.attempts == len(_DELAYS) + 1, (
        "the writer must make exactly one attempt per backoff delay plus the "
        "initial one - a different count means it is not routing through "
        "core.polled_json._replace_with_retry")
    assert _scratches(dest) == [], "an exhausted retry must strand no scratch"


# ------------------------------------------------------- W2: the scratch name
@pytest.mark.parametrize(
    "which",
    _DIRECT_WRITERS)
def test_writer_does_not_derive_its_scratch_from_the_destination_alone(
        tmp_path, writers, which):
    """Two writers of one control file must not share a scratch path.

    `str(dest) + ".tmp"` is a function of the DESTINATION only, so every writer
    of STOP opens the same STOP.tmp and their writes interleave. Capturing the
    `src` handed to os.replace is what distinguishes a per-writer scratch from
    the shared one; asserting on the directory listing afterwards cannot, since
    a successful write leaves nothing behind either way.
    """
    _mod, write = writers[which]
    dest = tmp_path / "STOP"
    seen: list[str] = []
    real_replace = os.replace

    def _spy(src, dst, *a, **kw):
        if Path(dst) == dest:
            seen.append(Path(src).name)
        return real_replace(src, dst, *a, **kw)

    os.replace = _spy
    try:
        write(dest, "first")
    finally:
        os.replace = real_replace

    os.replace = _spy
    try:
        write(dest, "second")
    finally:
        os.replace = real_replace

    assert len(seen) == 2, "the writer never reached os.replace with that dest"
    assert seen[0] != dest.name + ".tmp", (
        f"{which} still derives its scratch name from the destination alone "
        f"({seen[0]}), so two concurrent writers of this file share it")
    # The negative above rules out the ONE known-bad name without pinning
    # anything down - `dest.name + ".bak"` would satisfy it and still be shared
    # by every writer (feedback_negative_assertion_rules_out_without_pinning_
    # down). Two writes must therefore produce two DIFFERENT scratch names,
    # which is the property that actually makes concurrent writers safe.
    assert seen[0] != seen[1], (
        f"{which} reused the scratch name {seen[0]} across two writes, so it "
        f"is per-DESTINATION rather than per-WRITER and concurrent writers "
        f"still collide")


# ------------------------------------------------------------------- W3: bytes
def test_loop_controller_awrite_writes_lf_verbatim(tmp_path, controller):
    """awrite used Path.write_text, which turns LF into CRLF on Windows.

    Round-tripping through read_text hides this, so the assertion is on raw
    bytes. cycle.txt and STOP reasons are machine-read, and a byte count that
    disagrees with the file is a lie in a status line.
    """
    dest = tmp_path / "cycle.txt"
    controller.awrite(dest, "line one\nline two\n")
    assert dest.read_bytes() == b"line one\nline two\n"


# --------------------------------------------- the sys.path constraint, guarded
def test_absolute_path_load_still_resolves_the_atomic_writer(monkeypatch):
    """The fix must survive the context production actually loads these in.

    loop_controller.py:36 - "loaded by absolute file path (launcher + tests),
    so ops/loop is never on sys.path". The repo root is absent too, so a plain
    `import core.polled_json` raises ModuleNotFoundError there. This test
    removes the repo root from sys.path and evicts every cached `core` module,
    then loads all SEVEN swept writers by path and asserts each still reached a
    working atomic writer. Without this guard the bind could regress to a bare
    import and stay green here while crashing the controller on launch.

    Seven, not three: RM-250 named three siblings and cycle 48's adversarial
    pass refuted that count, so the loop below is driven by `_SWEPT_MODULES`
    rather than a hardcoded triple. This paragraph said "three" until the
    verifier caught it disagreeing with the code it documents - which is the
    same defect class (docstring asserts one thing, code does another) that
    this lane audits for, so it is corrected here rather than left as a nit.
    """
    monkeypatch.setattr(
        sys, "path",
        [p for p in sys.path if p and Path(p).resolve() != _ROOT])
    for name in [n for n in list(sys.modules) if n == "core" or
                 n.startswith("core.")]:
        monkeypatch.delitem(sys.modules, name, raising=False)
    # Evicting `core*` alone is NOT enough, and the first version of this test
    # proved it: `_bind_path` short-circuits on `if modname in sys.modules`, so
    # a cached - or deliberately faked - `rc_core_polled_json` satisfied the
    # assertion without any bind ever running. Seeding that name with a stub
    # whose atomic_write_bytes is `lambda p, d: None` made this test pass, which
    # is the textbook vacuous guard. The bind name must go too.
    monkeypatch.delitem(sys.modules, "rc_core_polled_json", raising=False)
    for stem in _SWEPT_MODULES:
        monkeypatch.delitem(sys.modules, f"{stem}_uut_cycle48", raising=False)
        monkeypatch.delitem(sys.modules, f"{stem}_isolated_cycle48",
                            raising=False)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("core.polled_json")

    real_pj = (_ROOT / "core" / "polled_json.py").resolve()
    for stem in _SWEPT_MODULES:
        monkeypatch.delitem(sys.modules, "rc_core_polled_json", raising=False)
        spec = importlib.util.spec_from_file_location(
            f"{stem}_isolated_cycle48", _OPS_LOOP / f"{stem}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{stem}_isolated_cycle48"] = mod
        spec.loader.exec_module(mod)
        writer = getattr(mod, "_atomic_write_bytes", None)
        assert callable(writer), (
            f"ops/loop/{stem}.py did not resolve an atomic byte writer when "
            f"the repo root is off sys.path - this is the launcher's context")
        # "A name resolved" is not "the right file was found". Pin the writer
        # to the REAL core/polled_json.py, so a wrong parents[N] or a typo'd
        # filename in any of the seven bind blocks fails here instead of
        # shipping green - each module computes that path independently.
        origin = Path(sys.modules[writer.__module__].__file__).resolve()
        assert origin == real_pj, (
            f"ops/loop/{stem}.py bound {origin}, not {real_pj} - its "
            f"absolute-path fallback resolves the wrong file")


# ----------------------------------------- the structural guard over ops/loop
def test_no_ops_loop_module_hand_rolls_an_atomic_write():
    """No module under ops/loop may call os.replace or Path.write_text again.

    Three of the seven writers swept this cycle - lanes.repoint_lane_pid,
    done_sentinel and claude_stub - write from inside larger functions with no
    directly callable (path, text) shape, so the behavioural tests above cannot
    reach them. This is what covers them, and it is also what stops an eighth
    hand-rolled writer from being added later: the defect class is "someone
    re-derived the atomic write", and the whole class is visible in the AST.

    AST, not grep, and that distinction is load-bearing here rather than
    stylistic. A text scan for `os.replace` over ops/loop returns TEN hits in
    this tree and every single one is prose - module docstrings and the very
    comments this cycle wrote explaining why the bare call was removed. A grep
    guard would have been permanently red on its own documentation
    (reference_ast_guard_string_scan_traps).
    """
    offenders = []
    for path in sorted(_OPS_LOOP.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not isinstance(fn, ast.Attribute):
                continue
            if (fn.attr == "replace" and isinstance(fn.value, ast.Name)
                    and fn.value.id == "os"):
                offenders.append(f"{path.name}:{node.lineno} os.replace")
            elif fn.attr == "write_text":
                offenders.append(f"{path.name}:{node.lineno} .write_text")

    assert offenders == [], (
        "ops/loop modules must route every atomic write through "
        "core.polled_json (atomic_write_bytes), which supplies the bounded "
        "PermissionError retry, a per-writer scratch name and cleanup on "
        "failure. Hand-rolled writers found: " + ", ".join(offenders))
