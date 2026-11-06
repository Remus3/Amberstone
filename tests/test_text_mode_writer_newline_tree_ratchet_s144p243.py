"""RM-1744 (RM-481 residual) - no text-mode file writer in the production tree emits CRLF by default.

On Windows a text-mode ``open(p, "w")`` / ``Path.write_text`` / ``os.fdopen(fd, "w")`` translates every ``\\n`` to
``\\r\\n`` unless ``newline="\\n"`` (or ``""``) is passed, and ``csv.writer`` ends rows with ``\\r\\n`` on every OS
unless ``lineterminator=`` is set. RM-481 / RM-441 swept the writers one family at a time
(tests/test_tracked_writer_lf_sweep.py covers a NAMED list of regenerators). This module is the tree-wide ratchet the
per-family guards lacked: every tracked, non-test Python module is scanned with ``ast``.

Measured 2026-11-06 over the tracked tree (tests, ``agents/agent3_testing`` suite code and the vendored fleet kit
excluded): 10 offending calls in 6 files, ALL in files this lane may not edit - frozen (``core/log_setup.py``,
``ops/rc_dev_runtime.py``, ``ops/rc_supervisor.py``) or PKG-owned (``ops/launcher/service_host.py``,
``ops/loop/slots.py`` - byte-pinned across repos, ``tools/run_packaged_smoke.py``). They are the baseline below, which
only shrinks. Any other file with such a call fails ``test_no_new_default_newline_text_writer``.

A scan is a claim about its own pattern, so ``test_scanner_is_live`` proves each shape is reported and each LF-safe
spelling is quiet. ``tools/run_phase2_smoke.py`` wraps ``sys.stdout.buffer`` in ``io.TextIOWrapper`` (console, not a
file) and is deliberately not a writer shape here.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_WRITE_CHARS = "wax+"
_MODE_RE = re.compile(r"^[rwxabt+U]+$")  # a bare mode string, not a path or "w:gz" archive mode
# tempfile constructors take (mode, ...) first; Path.open(mode) is handled by the receiver check below.
_MODE_FIRST = ("NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile")

# file -> count of offending calls. Frozen (CLAUDE.md) or PKG-owned or cross-repo byte-pinned: not a repo-lane edit.
_BASELINE = {
    "core/log_setup.py": 2,
    "ops/launcher/service_host.py": 1,
    "ops/loop/slots.py": 2,
    "ops/rc_dev_runtime.py": 3,
    "ops/rc_supervisor.py": 1,
    "tools/run_packaged_smoke.py": 1,
}

_OUT_OF_SCOPE_PREFIXES = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/")


def _in_scope(rel: str) -> bool:
    return not (rel.startswith(_OUT_OF_SCOPE_PREFIXES) or "/tests/" in rel)


def _const_str(node: ast.AST | None):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def scan_source(src: str) -> list[tuple[int, str]]:
    """(line, shape) of every default-newline text-mode writer call in ``src``."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
        kws = {k.arg: k.value for k in node.keywords}
        if name == "write_text":
            if "newline" not in kws:
                hits.append((node.lineno, "write_text"))
            continue
        if name in ("open", "fdopen", "NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"):
            mode = _const_str(kws.get("mode"))
            if mode is None and node.args:
                # builtin open(file, mode) / os.fdopen(fd, mode) / Path.open(mode)
                pos = 0 if (name in _MODE_FIRST or (isinstance(fn, ast.Attribute) and name == "open"
                                                    and not _is_module_name(fn.value))) else 1
                if len(node.args) > pos:
                    mode = _const_str(node.args[pos])
            if (mode and _MODE_RE.match(mode) and "b" not in mode and any(c in mode for c in _WRITE_CHARS)
                    and "newline" not in kws):
                hits.append((node.lineno, f"{name} {mode}"))
            continue
        if (name in ("writer", "DictWriter") and isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name) and fn.value.id == "csv"
                and "lineterminator" not in kws):
            hits.append((node.lineno, f"csv.{name}"))
    return hits


def _is_module_name(node: ast.AST) -> bool:
    """``io.open`` / ``os.fdopen``-style receivers take (file, mode); a Path receiver takes (mode)."""
    return isinstance(node, ast.Name) and node.id in ("io", "os", "codecs", "tempfile")


def _tree_counts() -> dict[str, int]:
    files = [(relative_posix(p), p) for p in repo_files(REPO_ROOT, ("*.py",))]
    assert len(files) > 200, "the tracked-file walk returned almost nothing"
    counts: dict[str, int] = {}
    for rel, path in files:
        if not _in_scope(rel):
            continue
        try:
            src = Path(path).read_text(encoding="utf-8")
            hits = scan_source(src)
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        if hits:
            counts[rel] = len(hits)
    return counts


def test_no_new_default_newline_text_writer():
    counts = _tree_counts()
    new = {rel: n for rel, n in counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, (
        "text-mode writers without newline= (CRLF on Windows) - pass newline=\"\\n\" "
        f"(csv: lineterminator=\"\\n\"), file: count: {new}"
    )


def test_baseline_is_exact():
    """A baseline entry that no longer offends (or offends less) must be lowered / dropped: it only shrinks."""
    counts = _tree_counts()
    stale = {rel: (n, counts.get(rel, 0)) for rel, n in _BASELINE.items() if counts.get(rel, 0) != n}
    assert not stale, f"baseline entries out of date, file: (baseline, measured): {stale}"


def test_scanner_is_live():
    bad = {
        'open(p, "w")': "open(p, 'w')",
        'open(p, mode="a")': "open(p, mode='a')",
        "Path.open": "p.open('w')",
        "io.open": "import io\nio.open(p, 'w')",
        "fdopen": "import os\nos.fdopen(fd, 'w')",
        "write_text": "p.write_text('x')",
        "NamedTemporaryFile": "import tempfile\ntempfile.NamedTemporaryFile(mode='w')",
        "csv.writer": "import csv\ncsv.writer(f)",
        "csv.DictWriter": "import csv\ncsv.DictWriter(f, fieldnames=[])",
    }
    for label, src in bad.items():
        assert scan_source(src), f"scanner missed {label}"
    good = [
        "open(p)",
        "open(p, 'r')",
        "open(p, 'rb')",
        "open(p, 'wb')",
        "open(p, 'w', newline='\\n')",
        "p.open('w', newline='')",
        "os.fdopen(fd, 'wb')",
        "os.fdopen(fd, 'w', newline='\\n')",
        "p.write_text('x', newline='\\n')",
        "import csv\ncsv.writer(f, lineterminator='\\n')",
        "import tempfile\ntempfile.NamedTemporaryFile(mode='wb')",
        "import tempfile\ntempfile.NamedTemporaryFile()",
    ]
    for src in good:
        assert not scan_source(src), f"scanner flagged an LF-safe spelling: {src!r}"


def test_scope_is_not_vacuous():
    """The scope keeps production code and drops test code; the baseline files are all inside it and tracked."""
    assert _in_scope("core/polled_json.py")
    assert not _in_scope("tests/test_x.py")
    assert not _in_scope("agents/daemon_slayer/tests/test_x.py")
    assert not _in_scope("agents/agent3_testing/suite/test_round12.py")
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _BASELINE:
        assert rel in tracked and _in_scope(rel), rel
