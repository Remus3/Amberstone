"""RM-481 residual (S144-P-279) - no production text-mode writer emits CRLF, pinned.

A text-mode ``open(p, "w")`` / ``Path.write_text(s)`` on Windows turns every ``\\n`` into
``\\r\\n`` unless it passes ``newline="\\n"`` (memory reference_windows_write_text_crlf_byte_count:
``read_text`` translates it back, so a string-equality test cannot see it). The RM-481 / RM-448
slices converted the DS extractors and table writers one module at a time; this is the
tree-wide measurement that closes the residual, and a ratchet so a new writer cannot
reintroduce it.

Measured 2026-11-06 with an AST walk over every tracked ``*.py`` outside the test trees:
TWELVE call sites lack ``newline=``, and every one is a file the lane may not edit (a frozen
file, the vendored fleet kit, or the PKG-owned launcher / packaged-smoke paths) - see
``_BASELINE``. There is NO other offender, no ``tools/*extract*`` writer among them.

Scope: tracked ``*.py`` excluding ``tests/`` and any ``<dir>/tests/``, ``agents/agent3_testing/suite/`` (test code
that writes tmp_path files) and ``docs/_archive/``. Only constant modes are read: a mode
held in a variable is invisible to this scan (named blind spot, as every AST ratchet here).
The baseline only shrinks: a baseline file that stops offending fails the exact-match test
until its row is dropped.
"""
from __future__ import annotations

import ast
import collections
import re

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_OUT_OF_SCOPE = ("tests/", "agents/agent3_testing/suite/", "docs/_archive/")
_MODE = re.compile(r"^[rwxa][bt+]*$")

# file -> number of call sites without newline=. Each row is a path this lane does not own.
_BASELINE = {
    "core/log_setup.py": 2,            # FROZEN (CLAUDE.md frozen list)
    "ops/rc_dev_runtime.py": 3,        # FROZEN
    "ops/rc_supervisor.py": 1,         # FROZEN (ASKS 24)
    "ops/fleet_kit/fleet_lanes.py": 2,  # vendored kit, byte-pinned by MANIFEST.json
    "ops/loop/slots.py": 2,            # SHARED_SHA256 cross-repo byte pin
    "ops/launcher/service_host.py": 1,  # PKG, main session owns
    "tools/run_packaged_smoke.py": 1,  # PKG, main session owns
}


def _mode_of(call: ast.Call) -> str | None:
    """The constant text mode a call opens with, or None when it is not a text-write open."""
    fn = call.func
    name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
    if name not in ("open", "fdopen"):
        return None
    mode = None
    # builtin open(file, mode) / os.fdopen(fd, mode) carry the mode second; Path.open(mode) first.
    path_open = name == "open" and isinstance(fn, ast.Attribute) and not (
        isinstance(fn.value, ast.Name) and fn.value.id in ("io", "os", "codecs", "gzip", "bz2", "lzma"))
    idx = 0 if path_open else 1
    if len(call.args) > idx and isinstance(call.args[idx], ast.Constant):
        mode = call.args[idx].value
    for kw in call.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            mode = kw.value.value
    if not isinstance(mode, str) or not _MODE.match(mode):
        return None
    if "b" in mode or not any(c in mode for c in "wax"):
        return None
    return mode


def crlf_sites(source: str) -> list[tuple[int, str]]:
    """(line, kind) of every text-mode writer in ``source`` that does not pass newline=."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if any(kw.arg == "newline" for kw in node.keywords):
            continue
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr == "write_text":
            out.append((node.lineno, "write_text"))
            continue
        mode = _mode_of(node)
        if mode is not None:
            out.append((node.lineno, f"open {mode}"))
    return out


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    paths = repo_files(REPO_ROOT, ("*.py",))
    assert len(paths) > 500, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for p in paths:
        rel = relative_posix(p)
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            sites = crlf_sites(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        if sites:
            counts[rel] = len(sites)
    return dict(counts)


def test_no_new_text_mode_writer_without_newline(tree_counts):
    new = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not new, f"text-mode writer(s) without newline=: {new} - pass newline=\"\\n\""


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) is dropped, so it only shrinks."""
    assert tree_counts == _BASELINE


def test_no_extractor_or_tools_writer_in_baseline():
    assert not [f for f in _BASELINE if f.startswith("tools/") and "extract" in f]


def test_scan_sees_each_writer_shape():
    src = (
        "from pathlib import Path\n"
        "import os\n"
        "Path('a').write_text('x')\n"
        "open('b', 'w')\n"
        "open('c', mode='a', encoding='utf-8')\n"
        "Path('d').open('w')\n"
        "os.fdopen(3, 'w')\n"
    )
    kinds = sorted(k for _, k in crlf_sites(src))
    assert kinds == ["open a", "open w", "open w", "open w", "write_text"]


def test_scan_passes_the_converted_shapes():
    src = (
        "from pathlib import Path\n"
        "Path('a').write_text('x', newline='\\n')\n"
        "open('b', 'w', newline='\\n')\n"
        "open('c', 'wb')\n"
        "open('d')\n"
        "open('e', 'r')\n"
        "webbrowser.open('data.json')\n"
    )
    assert crlf_sites(src) == []
