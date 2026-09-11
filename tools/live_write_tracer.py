#!/usr/bin/env python3
"""Pytest plugin - attribute LIVE-TREE writes to the test that caused them.

Load it with `-p tools.live_write_tracer`. Merely importing this module does
nothing; all patching happens in `pytest_configure` and is undone in
`pytest_unconfigure`. It is ALSO a small CLI, but only for merging reports:
`python tools/live_write_tracer.py --help`. There is deliberately no "run the
suite for me" mode - the tracer measures whatever pytest invocation you point
it at, and hiding that invocation would hide what was measured.

WHY A PLUGIN AND NOT A BEFORE/AFTER SNAPSHOT DIFF
-------------------------------------------------
A sibling repo measured a 300-second IDLE control on this box - no suite
running at all - and live files under `logs/`, `data/` and `ops/runtime/`
changed anyway, because the supervisor, the coaches and other concurrent
Claude sessions write those trees continuously. A filesystem diff taken
around a suite run therefore attributes NOTHING: every observed delta has at
least two plausible authors. This plugin is PROCESS-LOCAL, so no other writer
on the machine can contaminate it - if an event is recorded here, this pytest
process performed it.

WHAT IS COUNTED, AND IN WHAT UNIT
---------------------------------
DATA ACTUALLY WRITTEN, never opens. Opening a log for append and writing
nothing is not a write, and the report separates those two cases so a reader
cannot confuse them:

  wrote_units            data reaching each watched path, EXCLUDING atomic tmp
  written_by             nodeids whose open()-handle writes hit that path
  replaced_by            nodeids that landed that path via os.replace/os.rename
  atomic_tmp_units       data written through a `*.tmp` sibling that a rename
                         later landed on a watched path - reported separately
                         and NOT summed into totals, because the destination is
                         already credited by `replaced_by` and counting both
                         double-counts every atomic write in the tree
  opened_for_write_only  nodeids that opened a watched path in a write mode
                         and wrote zero units through it (paths that received
                         data by any route are omitted from this map)

THE UNIT IS NOT ALWAYS A BYTE, and the field is named `wrote_units` for that
reason. A write through a TEXT handle is measured in CHARACTERS, because that
is what the caller handed `write()` and the only honest thing this wrapper can
see without re-encoding. On Windows a text handle also translates each "\\n"
into CRLF on the way to disk, so for a line-oriented payload the on-disk byte
count is the character count PLUS the line count, and for non-ASCII text it is
larger again by the UTF-8 expansion. Binary handles and the rename path are
exact. Treat every text-mode figure as a LOWER BOUND on bytes, never as a
byte count - an earlier draft of this docstring said "bytes actually written"
and was wrong in exactly that direction.

`replaced_by` exists because the repo-standard atomic write
(`tmp.write_text(...); tmp.replace(target)`) is INVISIBLE to an open() wrapper
alone - the only path that wrapper ever sees is the TMP name, and the real
destination is only ever touched by the rename. The destination is credited
with the size of the source file as measured immediately before the rename.
Consequently a path written purely atomically shows units in `wrote_units`
and nodeids in `replaced_by` while its `written_by` list stays empty; that is
the signature of a correct atomic write, not a gap in the trace.

STATED LIMIT - SUBPROCESSES ARE INVISIBLE
-----------------------------------------
This tracer wraps `builtins.open`, `io.open`, `os.replace` and `os.rename` in
THIS interpreter only. A test that shells out - subprocess, os.system, a
spawned supervisor, a `py_compile` in a child, an AHK or PowerShell call -
can write anywhere in the live tree and this report will show nothing for it.
A clean report means "no live-tree writes from in-process code", never "no
live-tree writes". There is no fix for this short of a filesystem filter
driver, and a filter driver would reintroduce the third-party-writer problem
the plugin exists to avoid.

CONFIGURATION
-------------
  RC_TRACER_ROOT    repo root override; default is this file's grandparent
  RC_TRACER_REPORT  report path; default
                    <system temp>/rc_live_write_trace/live_write_trace.json

The default deliberately sits OUTSIDE the repo. An earlier draft defaulted to
`<root>/ops/runtime/live_write_trace.json`, which made the instrument a writer
in the very tree it polices - self-excluded from its own count, so it would
never have reported itself.

UNDER XDIST THE REPORT IS SPLIT, AND YOU MUST MERGE IT
------------------------------------------------------
Every xdist worker is a separate process running its own copy of this plugin,
so each writes its own file suffixed with its worker id, plus one for the
controller process. Reading any single one of them under-counts, and the
controller's file is nearly EMPTY because the controller runs no tests - which
is the dangerous case, since it looks like a clean census rather than a
partial one. Merge them:

    python tools/live_write_tracer.py --merge <dir-holding-the-reports>
"""
from __future__ import annotations

import argparse
import builtins
import io
import json
import os
import tempfile
import threading

import pytest

# Subtrees of the repo root that hold OPERATOR state - anything a suite writes
# here survives the run and is therefore a finding. Everything else in the repo
# (source, tests, docs) is either read-only to a suite or already covered by
# `git status`, so tracing it would only add noise.
_WATCH_SUBTREES = ("ops/runtime", "logs", "data", "moon_sync_inbox")

# Exact repo-root files worth watching. `restart_trigger.txt` is load-bearing:
# writing it bounces the live supervisor, so a test that touches it restarts
# the operator's running stack as a side effect.
_WATCH_ROOT_FILES = ("restart_trigger.txt",)

# The cross-repo slot namespace (ops/loop/slots.py:39 DEFAULT_ROOT's parent).
# It is outside every participating repository on purpose, which is exactly why
# a repo-relative watch set would miss writes that throttle sibling projects.
_EXTRA_WATCH_ROOTS = (r"C:\ProgramData\lw-loop",)

# A pytest tmp_path always carries this segment. Excluding it by SEGMENT rather
# than by prefix also catches a `--basetemp` pointed somewhere unusual.
_TMP_PATH_MARKER = "pytest-of-"

_SESSION_NODEID = "<collection-or-session>"

# The scratch half of the repo-standard atomic write. Matched by SUFFIX rather
# than by a per-writer pattern because `path.with_suffix(path.suffix + ".tmp")`
# and `path.with_suffix(".tmp")` produce different names and both are in use.
_ATOMIC_TMP_SUFFIX = ".tmp"

_state = None


class _Tracer:
    """Mutable run state - instantiated in pytest_configure, never at import."""

    def __init__(self, root, report):
        self.root = root
        self.root_norm = os.path.normcase(root)
        self.report = report
        self.report_norms = {
            os.path.normcase(report),
            os.path.normcase(report + ".tmp"),
        }
        self.extra_roots = tuple(
            os.path.normcase(os.path.abspath(p)) for p in _EXTRA_WATCH_ROOTS
        )
        self.tempdir_norm = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
        self.nodeid = _SESSION_NODEID
        self.lock = threading.Lock()
        self.wrote_units = {}
        self.atomic_tmp_units = {}
        self.written_by = {}
        self.replaced_by = {}
        # One record per watched write-open, so a handle that is never closed
        # (leaked, or GC'd after the report) is still accounted for.
        self.open_records = []
        self.orig_open = None
        self.orig_io_open = None
        self.orig_replace = None
        self.orig_rename = None

    def key_for(self, path):
        """Report key for a watched path, or None when the path is not watched."""
        if isinstance(path, int) or not isinstance(path, (str, bytes, os.PathLike)):
            return None
        disp = os.path.abspath(os.fsdecode(os.fspath(path)))
        norm = os.path.normcase(disp)
        if _TMP_PATH_MARKER in norm:
            return None
        if norm in self.report_norms:
            return None
        if norm == self.tempdir_norm or norm.startswith(self.tempdir_norm + os.sep):
            return None
        for extra in self.extra_roots:
            if norm == extra or norm.startswith(extra + os.sep):
                return disp.replace("\\", "/")
        if not norm.startswith(self.root_norm + os.sep):
            return None
        rel = os.path.relpath(disp, self.root).replace("\\", "/")
        rel_norm = rel.lower()
        if rel_norm in _WATCH_ROOT_FILES:
            return rel
        for sub in _WATCH_SUBTREES:
            if rel_norm == sub or rel_norm.startswith(sub + "/"):
                return rel
        return None

    def credit_units(self, key, count, nodeid, record=None):
        with self.lock:
            if key.endswith(_ATOMIC_TMP_SUFFIX):
                # The repo-standard atomic write is `tmp.write(...)` then
                # `tmp.replace(target)`, and BOTH the tmp and the destination
                # sit inside a watched subtree. Crediting the tmp into the
                # same total as the rename counts every atomic write twice, so
                # the tmp half gets its own bucket that totals never sum.
                self.atomic_tmp_units[key] = self.atomic_tmp_units.get(key, 0) + count
            else:
                self.wrote_units[key] = self.wrote_units.get(key, 0) + count
                _append_unique(self.written_by, key, nodeid)
            if record is not None:
                record["units"] += count

    def credit_replace(self, key, count, nodeid):
        with self.lock:
            self.wrote_units[key] = self.wrote_units.get(key, 0) + count
            _append_unique(self.replaced_by, key, nodeid)


def _append_unique(mapping, key, value):
    """Ordered-set append - first-seen order survives into the JSON report."""
    seen = mapping.setdefault(key, [])
    if value not in seen:
        seen.append(value)


def _datalen(data):
    """Length in the unit the caller wrote - characters for text, bytes for binary."""
    if isinstance(data, str):
        return len(data)
    if isinstance(data, memoryview):
        return data.nbytes
    try:
        return len(data)
    except TypeError:
        return 0


class _CountingHandle:
    """Delegating proxy that counts what is written through a watched handle.

    A proxy is unavoidable: `_io.TextIOWrapper.write` is read-only, so the
    instance cannot be patched in place. Its blast radius is deliberately kept
    to watched write-opens only - every other open() returns the real object
    untouched, so ordinary test I/O never meets this class.
    """

    __slots__ = ("_rc_handle", "_rc_key", "_rc_tracer", "_rc_record")

    def __init__(self, handle, key, tracer, record):
        self._rc_handle = handle
        self._rc_key = key
        self._rc_tracer = tracer
        self._rc_record = record

    def write(self, data):
        result = self._rc_handle.write(data)
        try:
            count = _datalen(data)
            if count:
                self._rc_tracer.credit_units(
                    self._rc_key, count, self._rc_tracer.nodeid, self._rc_record
                )
        except Exception:  # noqa: BLE001 - tracing must never fail a test
            pass
        return result

    def writelines(self, lines):
        # Materialised because an iterator would be consumed by the measurement.
        chunks = list(lines)
        result = self._rc_handle.writelines(chunks)
        try:
            count = sum(_datalen(chunk) for chunk in chunks)
            if count:
                self._rc_tracer.credit_units(
                    self._rc_key, count, self._rc_tracer.nodeid, self._rc_record
                )
        except Exception:  # noqa: BLE001 - tracing must never fail a test
            pass
        return result

    def __getattr__(self, name):
        # object.__getattribute__ does not re-enter __getattr__, so a half-built
        # proxy raises AttributeError instead of recursing to a stack overflow.
        return getattr(object.__getattribute__(self, "_rc_handle"), name)

    def __enter__(self):
        self._rc_handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._rc_handle.__exit__(*exc)

    def __iter__(self):
        return iter(self._rc_handle)

    def __next__(self):
        return next(self._rc_handle)


def _is_write_mode(mode):
    try:
        text = mode if isinstance(mode, str) else str(mode)
    except Exception:  # noqa: BLE001 - tracing must never fail a test
        return False
    return any(flag in text for flag in ("w", "a", "x", "+"))


def _make_open(tracer):
    def _traced_open(file, mode="r", *args, **kwargs):
        handle = tracer.orig_open(file, mode, *args, **kwargs)
        try:
            if not _is_write_mode(mode):
                return handle
            key = tracer.key_for(file)
            if key is None:
                return handle
            record = {"key": key, "nodeid": tracer.nodeid, "units": 0}
            with tracer.lock:
                tracer.open_records.append(record)
            return _CountingHandle(handle, key, tracer, record)
        except Exception:  # noqa: BLE001 - tracing must never fail a test
            return handle

    return _traced_open


def _make_mover(tracer, original):
    def _traced_mover(src, dst, **kwargs):
        key = None
        size = 0
        try:
            key = tracer.key_for(dst)
            if key is not None:
                # Measured BEFORE the move - after it the source is gone, and
                # the destination may be overwritten by a later rename.
                size = os.path.getsize(src)
        except Exception:  # noqa: BLE001 - tracing must never fail a test
            pass
        result = original(src, dst, **kwargs)
        try:
            if key is not None:
                tracer.credit_replace(key, size, tracer.nodeid)
        except Exception:  # noqa: BLE001 - tracing must never fail a test
            pass
        return result

    return _traced_mover


def _build_report(tracer):
    opened_only = {}
    for record in tracer.open_records:
        if record["units"]:
            continue
        # A path that received data by ANY route is not "opened only", even if
        # some other handle on it wrote nothing.
        if tracer.wrote_units.get(record["key"]):
            continue
        _append_unique(opened_only, record["key"], record["nodeid"])
    tests = set()
    for mapping in (tracer.written_by, tracer.replaced_by, opened_only):
        for nodeids in mapping.values():
            tests.update(nodeids)
    files = set(tracer.wrote_units) | set(tracer.replaced_by) | set(opened_only)
    return {
        "wrote_units": dict(sorted(tracer.wrote_units.items())),
        "atomic_tmp_units": dict(sorted(tracer.atomic_tmp_units.items())),
        "written_by": dict(sorted(tracer.written_by.items())),
        "replaced_by": dict(sorted(tracer.replaced_by.items())),
        "opened_for_write_only": dict(sorted(opened_only.items())),
        "totals": {
            "files": len(files),
            "units": sum(tracer.wrote_units.values()),
            "tests": len(tests),
        },
    }


def _write_report(tracer):
    payload = json.dumps(_build_report(tracer), indent=2, sort_keys=True)
    parent = os.path.dirname(tracer.report)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = tracer.report + ".tmp"
    # The saved originals, not the live builtins - the report must not be able
    # to trace itself, and unconfigure may not have run yet.
    with tracer.orig_open(tmp, "w", encoding="ascii", newline="\n") as handle:
        handle.write(payload)
    tracer.orig_replace(tmp, tracer.report)


def _default_report_path():
    """Outside the repo, always.

    The instrument must not be a writer in the tree it polices. It excludes
    its own report from `key_for`, so a repo-relative default would have been
    the one live-tree write this tool could never report.
    """
    return os.path.join(tempfile.gettempdir(), "rc_live_write_trace",
                        "live_write_trace.json")


def _is_xdist_controller(config):
    """True in the xdist controller process, false in a worker and in a plain
    serial run (where there is exactly one report and nothing to disambiguate).
    """
    try:
        numprocesses = config.getoption("numprocesses", None)
    except (ValueError, AttributeError):
        return False
    return bool(numprocesses)


def merge_reports(paths):
    """Combine per-process reports into one census.

    Kept in the tool rather than written fresh at each call site: the first
    census this tracer produced was merged by a throwaway script, which is how
    a reader ends up quoting one worker's file as the whole answer.
    """
    paths = list(paths)  # consumed twice - once here, once for the count
    wrote_units = {}
    atomic_tmp_units = {}
    written_by = {}
    replaced_by = {}
    opened_only = {}
    for path in paths:
        with open(path, encoding="utf-8") as handle:
            report = json.load(handle)
        for key, value in report.get("wrote_units", {}).items():
            wrote_units[key] = wrote_units.get(key, 0) + value
        for key, value in report.get("atomic_tmp_units", {}).items():
            atomic_tmp_units[key] = atomic_tmp_units.get(key, 0) + value
        for name, dest in (("written_by", written_by),
                           ("replaced_by", replaced_by),
                           ("opened_for_write_only", opened_only)):
            for key, nodeids in report.get(name, {}).items():
                for nodeid in nodeids:
                    _append_unique(dest, key, nodeid)
    # A path credited with data by one worker is not "opened only" just
    # because another worker opened it and wrote nothing.
    opened_only = {k: v for k, v in opened_only.items() if not wrote_units.get(k)}
    tests = set()
    for mapping in (written_by, replaced_by, opened_only):
        for nodeids in mapping.values():
            tests.update(nodeids)
    files = set(wrote_units) | set(replaced_by) | set(opened_only)
    return {
        "wrote_units": dict(sorted(wrote_units.items())),
        "atomic_tmp_units": dict(sorted(atomic_tmp_units.items())),
        "written_by": dict(sorted(written_by.items())),
        "replaced_by": dict(sorted(replaced_by.items())),
        "opened_for_write_only": dict(sorted(opened_only.items())),
        "totals": {
            "files": len(files),
            "units": sum(wrote_units.values()),
            "tests": len(tests),
            "reports_merged": len(paths),
        },
    }


def pytest_configure(config):
    global _state
    root = os.environ.get("RC_TRACER_ROOT")
    if not root:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root = os.path.abspath(root)
    report = os.environ.get("RC_TRACER_REPORT") or _default_report_path()
    report = os.path.abspath(report)
    # Under xdist every process - the CONTROLLER included - runs its own copy of
    # this plugin, so a single shared report path means the last one to finish
    # silently overwrites the rest and the census under-counts by a factor of
    # -n. Suffixing by process keeps one file per process, to be merged with
    # `--merge`. The controller is suffixed too, and that is the load-bearing
    # half: it runs no tests, so an unsuffixed controller report would sit at
    # the path the docs name looking like a CLEAN census while every actual
    # write sat in the worker files beside it.
    worker = os.environ.get("PYTEST_XDIST_WORKER") or (
        "controller" if _is_xdist_controller(config) else "")
    if worker:
        stem, ext = os.path.splitext(report)
        report = stem + "." + worker + ext
    tracer = _Tracer(root, report)
    tracer.orig_open = builtins.open
    tracer.orig_io_open = io.open
    tracer.orig_replace = os.replace
    tracer.orig_rename = os.rename
    # Published BEFORE any patching. If a raise landed between the first patch
    # and this assignment, `pytest_unconfigure` would short-circuit on
    # `_state is None` and leave builtins.open replaced for the life of the
    # process - the tracer would outlive its own run.
    _state = tracer
    try:
        traced_open = _make_open(tracer)
        builtins.open = traced_open
        # pathlib.Path.open (and therefore write_text, the repo's atomic-write
        # front half) calls io.open, which is a SEPARATE module attribute bound
        # to the same function - patching builtins alone would miss every Path
        # write. Its own original is captured above rather than assumed equal
        # to builtins.open, because another plugin may already have moved one
        # of the two.
        io.open = traced_open
        os.replace = _make_mover(tracer, tracer.orig_replace)
        os.rename = _make_mover(tracer, tracer.orig_rename)
    except Exception:  # noqa: BLE001 - never leave the process half-patched
        pytest_unconfigure(config)
        raise


def pytest_unconfigure(config):
    global _state
    tracer = _state
    if tracer is None:
        return
    try:
        if tracer.orig_open is not None:
            builtins.open = tracer.orig_open
        if tracer.orig_io_open is not None:
            io.open = tracer.orig_io_open
        if tracer.orig_replace is not None:
            os.replace = tracer.orig_replace
        if tracer.orig_rename is not None:
            os.rename = tracer.orig_rename
    finally:
        _state = None


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    # Wraps the WHOLE protocol, so a write from a fixture setup or teardown is
    # attributed to the test it serves rather than falling back to the session.
    tracer = _state
    if tracer is None:
        return (yield)
    previous = tracer.nodeid
    tracer.nodeid = item.nodeid
    try:
        return (yield)
    finally:
        tracer.nodeid = previous


def pytest_sessionfinish(session, exitstatus):
    tracer = _state
    if tracer is None:
        return
    try:
        _write_report(tracer)
    except Exception as exc:  # noqa: BLE001 - a missing report must not fail the run
        print(f"[live_write_tracer] report write failed: {exc!r}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="live_write_tracer",
        description=(
            "Merge the per-process reports this plugin writes. The plugin "
            "itself is loaded by pytest with `-p tools.live_write_tracer`; "
            "this CLI does not run tests."),
        epilog=(
            "example: python -m pytest tests -p tools.live_write_tracer -n 8 "
            "&& python tools/live_write_tracer.py --merge "
            "%TEMP%/rc_live_write_trace"),
    )
    parser.add_argument(
        "--merge", metavar="DIR_OR_FILE", nargs="+", required=True,
        help=("report files, or directories to scan for live_write_trace*.json. "
              "Under xdist there is one report per worker plus one for the "
              "controller, and reading a single file under-counts."))
    parser.add_argument(
        "--out", metavar="PATH", default="",
        help="write the merged census here instead of stdout")
    args = parser.parse_args(argv)

    files = []
    for target in args.merge:
        if os.path.isdir(target):
            files.extend(sorted(
                os.path.join(target, name) for name in os.listdir(target)
                if name.startswith("live_write_trace") and name.endswith(".json")))
        else:
            files.append(target)
    if not files:
        parser.error(f"no reports found under {args.merge}")
    payload = json.dumps(merge_reports(files), indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="ascii", newline="\n") as handle:
            handle.write(payload)
        print(f"merged {len(files)} report(s) -> {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
