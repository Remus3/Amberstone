"""S144-P-453 (RM-481 residual) - no production module builds or subclasses a stdlib file handler that writes CRLF.

The stdlib ``FileHandler._open`` passes no ``newline=``, so on Windows every log record's trailing LF becomes CRLF
(RM-481). The repo's answer is ``core.log_rotation.LF*FileHandler`` (or a private subclass that overrides ``_open``).
The per-module guards (tests/test_log_handlers_lf_s144p196.py, ...p197, ...p199) each pin a NAMED list of converted
modules, so a NEW module that wrote ``logging.FileHandler(path)`` passed every one of them, and
tests/test_text_mode_writer_newline_tree_ratchet_s144p243.py scans ``open`` / ``write_text`` / ``csv`` shapes only, never
a handler. This module is the tree-wide ratchet for handlers, in the same ``ast`` style over the tracked tree
(tests, ``agents/agent3_testing`` suite code and the vendored fleet kit excluded).

Three shapes are offences:
  1. a call that constructs ``FileHandler`` / ``RotatingFileHandler`` / ``TimedRotatingFileHandler`` /
     ``WatchedFileHandler`` (by bare or dotted name);
  2. ``logging.basicConfig(filename=...)``, which builds a stdlib ``FileHandler`` internally;
  3. a class whose base is one of those four and that does not define ``_open`` (the LF subclasses override it).

Measured 2026-11-08 at this tree: no call and no ``basicConfig`` offender; six handler subclasses, five of which
override ``_open`` (``core/log_rotation.py`` LFFileHandler / LFRotatingFileHandler and the three private
``_LFFileHandler`` copies in tools/) and ONE that does not: ``core/log_setup.py`` DailyRotatingFileHandler, a FROZEN file
(CLAUDE.md), so it is the baseline below, which only shrinks. A scan is a claim about its own pattern, so
``test_scanner_is_live`` proves every shape is reported and every LF-safe spelling is quiet.
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_STDLIB_HANDLERS = frozenset({"FileHandler", "RotatingFileHandler", "TimedRotatingFileHandler",
                              "WatchedFileHandler"})

# file -> count of offences. Frozen (CLAUDE.md) so not a repo-lane edit; the set only shrinks.
_BASELINE = {
    "core/log_setup.py": 1,  # class DailyRotatingFileHandler(RotatingFileHandler), no _open override
}

_OUT_OF_SCOPE_PREFIXES = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/")


def _in_scope(rel: str) -> bool:
    return not (rel.startswith(_OUT_OF_SCOPE_PREFIXES) or "/tests/" in rel)


def _name(node: ast.AST) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else getattr(node, "id", None)


def scan_source(src: str) -> list[tuple[int, str]]:
    """(line, shape) of every CRLF-by-default file-handler construction or subclass in ``src``."""
    hits: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            name = _name(node.func)
            if name in _STDLIB_HANDLERS:
                hits.append((node.lineno, f"call {name}"))
            elif name == "basicConfig" and any(k.arg == "filename" for k in node.keywords):
                hits.append((node.lineno, "basicConfig(filename=)"))
        elif isinstance(node, ast.ClassDef):
            bases = [b for b in (_name(b) for b in node.bases) if b in _STDLIB_HANDLERS]
            overrides = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_open"
                            for n in node.body)
            if bases and not overrides:
                hits.append((node.lineno, f"class {node.name}({bases[0]}) without _open"))
    return hits


def _tree_counts() -> dict[str, int]:
    files = [(relative_posix(p), p) for p in repo_files(REPO_ROOT, ("*.py",))]
    assert len(files) > 200, "the tracked-file walk returned almost nothing"
    counts: dict[str, int] = {}
    for rel, path in files:
        if not _in_scope(rel):
            continue
        try:
            hits = scan_source(Path(path).read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        if hits:
            counts[rel] = len(hits)
    return counts


def test_no_new_crlf_file_handler():
    counts = _tree_counts()
    new = {rel: n for rel, n in counts.items() if n > _BASELINE.get(rel, 0)}
    assert not new, (
        "stdlib file handlers write CRLF on Windows - use core.log_rotation.LFFileHandler / "
        f'LFRotatingFileHandler (or override _open with newline="\\n"), file: count: {new}'
    )


def test_baseline_is_exact():
    """A baseline entry that no longer offends (or offends less) must be lowered / dropped: it only shrinks."""
    counts = _tree_counts()
    stale = {rel: (n, counts.get(rel, 0)) for rel, n in _BASELINE.items() if counts.get(rel, 0) != n}
    assert not stale, f"baseline entries out of date, file: (baseline, measured): {stale}"


def test_scanner_is_live():
    bad = {
        "logging.FileHandler": "import logging\nlogging.FileHandler('a')",
        "bare FileHandler": "from logging import FileHandler\nFileHandler('a')",
        "RotatingFileHandler": "from logging.handlers import RotatingFileHandler\nRotatingFileHandler('a')",
        "TimedRotatingFileHandler": "import logging.handlers as h\nh.TimedRotatingFileHandler('a')",
        "WatchedFileHandler": "import logging.handlers as h\nh.WatchedFileHandler('a')",
        "basicConfig": "import logging\nlogging.basicConfig(filename='a')",
        "subclass": "import logging\nclass H(logging.FileHandler):\n    pass",
        "subclass of a bare name": "class H(RotatingFileHandler):\n    def emit(self, r):\n        pass",
    }
    for label, src in bad.items():
        assert scan_source(src), f"scanner missed {label}"
    good = [
        "from core.log_rotation import LFFileHandler\nLFFileHandler('a')",
        "from core.log_rotation import LFRotatingFileHandler\nLFRotatingFileHandler('a')",
        "import logging\nlogging.basicConfig(level=10)",
        "import logging\nlogging.StreamHandler()",
        "import logging\nclass H(logging.FileHandler):\n    def _open(self):\n        return None",
        "class H(SafeRotatingFileHandler):\n    pass",
    ]
    for src in good:
        assert not scan_source(src), f"scanner flagged an LF-safe spelling: {src!r}"


def test_scope_is_not_vacuous():
    """The scope keeps production code and drops test code; the baseline files are all inside it and tracked."""
    assert _in_scope("core/log_rotation.py")
    assert not _in_scope("tests/test_x.py")
    assert not _in_scope("agents/daemon_slayer/tests/test_x.py")
    assert not _in_scope("ops/fleet_kit/fleet_gitlock.py")
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _BASELINE:
        assert rel in tracked and _in_scope(rel), rel
    # the LF implementations the rule points at are inside the scan and pass it
    for rel in ("core/log_rotation.py", "tools/liveclient_relay.py", "tools/lcu_agent.py"):
        assert rel in tracked and _in_scope(rel)
        assert not scan_source((REPO_ROOT / rel).read_text(encoding="utf-8")), rel
