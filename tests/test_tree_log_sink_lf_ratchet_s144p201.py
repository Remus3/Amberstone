"""RM-481 residual (s144, RM-1711): a tree-wide ratchet on log sinks.

tests/test_tree_text_writer_lf_ratchet_s144p90.py guards the write-mode
text writers tree-wide but rules append-mode sinks out of scope, and the
stdlib file-handler checks (tests/test_log_handlers_lf_s144p196 .. p199) pin
NAMED files: a sink that is on no list was invisible, so every new log file
had to be remembered. This inverts that for the two families, the way the
RM-258 atomic-write guard does for tools/. EVERY tracked non-test .py is in
scope; a module may carry one of these shapes only through _BASELINE.

On Windows the text layer turns each record's trailing LF into CRLF unless
the open passes ``newline="\\n"``, and the stdlib ``FileHandler._open`` never
does. Four shapes offend:

  A. an append-mode text ``open`` / ``Path.open`` / ``os.fdopen`` with no
     ``newline=`` (a constant mode with ``a`` and no ``b``);
  B. a call that builds a stdlib FileHandler / RotatingFileHandler /
     TimedRotatingFileHandler / WatchedFileHandler (the LF subclasses in
     core.log_rotation, or a standalone module's inline copy, are the answer);
  C. a class that subclasses one of those stdlib handlers and defines no
     ``_open`` (it inherits the CRLF open);
  D. ``logging.basicConfig(filename=...)``, which builds a stdlib FileHandler.

Measured 2026-11-05 over the git index: three files offend, all owned
elsewhere (core/log_setup.py: shape C, RM-1709, and ops/rc_supervisor.py:
shape A, the supervisor log, are frozen; ops/launcher/service_host.py: shape A,
the packaging launcher, is the main session's), and the set only shrinks. A new sink starts guarded, and
an entry that stops offending fails test_baseline_is_exact until it is
dropped.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_STDLIB_FILE_HANDLERS = frozenset({
    "FileHandler", "RotatingFileHandler",
    "TimedRotatingFileHandler", "WatchedFileHandler",
})

# rel path -> why it may keep the shape. Only shrinks.
_BASELINE = {
    "core/log_setup.py": "frozen (CLAUDE.md); RM-1709 plan: inherit LFRotatingFileHandler",
    "ops/rc_supervisor.py": "frozen (CLAUDE.md); supervisor log append",
    "ops/launcher/service_host.py": "packaging launcher, main session owns (PKG)",
}


def _in_scope(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("tests/") or "/tests/" in rel:
        return False
    return not (name.startswith("test_") or name == "conftest.py")


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    return f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _const_str(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _open_mode(node: ast.Call) -> str | None:
    """The constant mode string of an open-shaped call, else None."""
    name = _call_name(node)
    f = node.func
    for kw in node.keywords:
        if kw.arg == "mode":
            return _const_str(kw.value)
    if name == "open":
        # builtin open(file, mode), io.open(file, mode), Path.open(mode)
        is_path_method = isinstance(f, ast.Attribute) and not (
            isinstance(f.value, ast.Name) and f.value.id in {"io", "codecs"})
        idx = 0 if is_path_method else 1
    elif name == "fdopen":
        idx = 1
    else:
        return None
    return _const_str(node.args[idx]) if len(node.args) > idx else None


def _violations(src: str) -> list[str]:
    out: list[str] = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call):
            name = _call_name(node)
            if name in {"open", "fdopen"}:
                mode = _open_mode(node)
                if (mode and "a" in mode and "b" not in mode
                        and not any(k.arg == "newline" for k in node.keywords)):
                    out.append(f"{node.lineno} A append open without newline=")
            if name in _STDLIB_FILE_HANDLERS:
                out.append(f"{node.lineno} B builds a stdlib {name}")
            if name == "basicConfig" and any(
                    k.arg == "filename" for k in node.keywords):
                out.append(f"{node.lineno} D basicConfig(filename=)")
        elif isinstance(node, ast.ClassDef):
            bases = {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                     for b in node.bases}
            defines_open = any(
                isinstance(n, ast.FunctionDef) and n.name == "_open"
                for n in node.body)
            if bases & _STDLIB_FILE_HANDLERS and not defines_open:
                out.append(f"{node.lineno} C {node.name} inherits the CRLF _open")
    return out


def _offenders() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for path in repo_files(REPO_ROOT, ("*.py",)):
        rel = relative_posix(path)
        if not _in_scope(rel):
            continue
        found = _violations(path.read_bytes().decode("utf-8"))
        if found:
            out[rel] = found
    return out


def test_walk_is_not_vacuous():
    rels = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for anchor in ("core/log_rotation.py", "tools/phase_watcher.py",
                   "core/coach_trace.py", "ops/rc_supervisor.py"):
        assert anchor in rels, anchor
    assert len(rels) > 500


def test_no_unclassified_crlf_log_sink():
    new = {r: v for r, v in _offenders().items() if r not in _BASELINE}
    assert not new, (
        "log sink that writes CRLF on Windows (append open without newline=, "
        "stdlib file handler, or a handler subclass with no _open): "
        f"{new}. Pass newline=\"\\n\" or use core.log_rotation.LF* handlers.")


def test_baseline_is_exact():
    offenders = _offenders()
    stale = sorted(r for r in _BASELINE if r not in offenders)
    assert not stale, f"no longer offend - drop from _BASELINE: {stale}"
    missing = [r for r in _BASELINE if not (REPO_ROOT / r).is_file()]
    assert not missing, f"not tracked files: {missing}"


def test_the_lf_handlers_this_ratchet_leans_on_still_pass():
    """Positive anchors: the LF handler homes and the inline standalone copies
    are scanned and clean, so the tree-wide pass is not riding on skipped files."""
    offenders = _offenders()
    for rel in ("core/log_rotation.py", "tools/liveclient_relay.py",
                "tools/phase_watcher.py", "tools/screen_agent.py",
                "tools/hotkey_listener.py", "core/coach_trace.py"):
        assert (REPO_ROOT / rel).is_file(), rel
        assert rel not in offenders, (rel, offenders.get(rel))


def test_detector_controls_positive_and_negative():
    bad_a = "open('x.log', 'a', encoding='utf-8')\n"
    assert [v for v in _violations(bad_a) if " A " in v]
    assert [v for v in _violations("from pathlib import Path\n"
                                   "Path('x').open('a')\n") if " A " in v]
    assert [v for v in _violations("import os\nos.fdopen(1, 'a')\n") if " A " in v]
    assert [v for v in _violations("open('x', mode='a')\n") if " A " in v]
    assert not _violations("open('x.log', 'a', encoding='utf-8', newline='\\n')\n")
    assert not _violations("open('x.log', 'ab')\n")
    assert not _violations("open('x.log', 'r')\n")
    assert not _violations("open('x.log', 'w')\n")  # write mode is the other ratchet
    assert [v for v in _violations("import logging\nlogging.FileHandler('a')\n")
            if " B " in v]
    assert [v for v in _violations(
        "from logging.handlers import RotatingFileHandler\n"
        "RotatingFileHandler('a')\n") if " B " in v]
    assert not _violations("from core.log_rotation import LFFileHandler\n"
                           "LFFileHandler('a')\n")
    assert [v for v in _violations(
        "import logging\nclass H(logging.FileHandler):\n    pass\n") if " C " in v]
    assert not _violations(
        "import logging\nclass H(logging.FileHandler):\n"
        "    def _open(self):\n        return None\n")
    assert not _violations("class H(LFRotatingFileHandler):\n    pass\n")
    assert [v for v in _violations(
        "import logging\nlogging.basicConfig(filename='x.log')\n") if " D " in v]
    assert not _violations("import logging\nlogging.basicConfig(level=10)\n")
