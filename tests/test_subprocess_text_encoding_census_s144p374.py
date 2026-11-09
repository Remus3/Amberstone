"""S144-P-374 - a text-mode subprocess spawn names how its child's bytes are decoded.

``subprocess.run(..., text=True)`` (or ``universal_newlines=True``) with no ``encoding=`` decodes the child's
stdout / stderr with ``locale.getpreferredencoding()``, which on Windows is the ANSI code page (cp1252), not
UTF-8. ``git`` and ``gh`` always write UTF-8, so a tracked path, a commit subject or a CI job name holding a
non-ASCII character is mis-decoded, and a byte cp1252 leaves undefined (0x81, 0x8D, 0x8F, 0x90, 0x9D, all of
which occur as UTF-8 continuation bytes) raises ``UnicodeDecodeError`` inside the reader instead of returning
text. A call that has no decode policy therefore fails on data, not on the code path a test exercises.
S144-P-372 closed the same gap for ``Path.read_text`` / ``write_text``; this is the subprocess sibling.

Rule: a ``subprocess`` spawn through the module or an import alias that passes ``text=`` or
``universal_newlines=`` (anything but a literal False) must also pass ``encoding=`` or ``errors=``. Native Windows
tools (tasklist, cmdkey, wmic, powershell) write the OEM / ANSI page, not UTF-8, so for those ``errors="replace"``
alone is the right decision: it keeps the locale decode and cannot raise. ``git`` / ``gh`` / a Python child take
``encoding="utf-8", errors="replace"``.

``_BASELINE`` (file -> offending-spawn count) is the measured remainder and only shrinks: a new file or a raised
count fails, and an entry that stops offending fails until it is dropped. The fleet kit and the frozen
``ops/rc_supervisor.py`` / ``ops/rc_dev_runtime.py`` pair are rows with their reason, not silent exclusions.

Stated limits: a ``**kwargs`` splat is trusted (the guard cannot see inside a parameter), a spawn through a
parameter named ``run`` (tools/gated_b29_window_parity.py's injected runner) or ``Popen`` with a positional
``encoding`` is not read, and ``os.popen`` / ``asyncio.create_subprocess_*`` are not covered.
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_FUNCS = frozenset({"run", "check_output", "check_call", "call", "Popen"})
_TEXT_KWS = frozenset({"text", "universal_newlines"})
_DECODE_KWS = frozenset({"encoding", "errors"})
_OUT_OF_SCOPE = ("tests/", "ops/fleet_kit/", "agents/agent3_testing/suite/", "docs/_archive/")

# file -> number of text-mode spawns with no decode policy. Only shrinks. Reasons per group:
#   frozen (ASKS 24, never edited from a lane): ops/rc_supervisor.py, ops/rc_dev_runtime.py
#   PKG, owned by the main session: tools/run_packaged_smoke.py
#   (S144-P-431 converted the ten native-Windows-tool and python-child rows, and S144-P-432 the last two,
#   tools/dev_cli.py and tools/sibling_sweep_ci.py: errors="replace" only, because a Python child writing
#   to a pipe uses the ANSI page, not UTF-8, so no single encoding= is right for a mixed caller.)
_BASELINE = {
    "ops/rc_dev_runtime.py": 1,
    "ops/rc_supervisor.py": 3,
    "tools/run_packaged_smoke.py": 5,
}


def _aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """(names bound to the subprocess module, bare names bound to a spawn function)."""
    mods: set[str] = set()
    funcs: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods.update((a.asname or a.name) for a in n.names if a.name == "subprocess")
        elif isinstance(n, ast.ImportFrom) and n.module == "subprocess":
            funcs.update((a.asname or a.name) for a in n.names if a.name in _FUNCS)
    return mods, funcs


def _is_false(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value in (False, None)


def undecoded_spawns(source: str) -> list[int]:
    """Lines of text-mode subprocess spawns that name neither ``encoding=`` nor ``errors=``."""
    tree = ast.parse(source)
    mods, funcs = _aliases(tree)
    lines: list[int] = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        f = n.func
        hit = (
            isinstance(f, ast.Attribute) and f.attr in _FUNCS
            and isinstance(f.value, ast.Name) and f.value.id in mods
        ) or (isinstance(f, ast.Name) and f.id in funcs)
        if not hit:
            continue
        if any(k.arg is None for k in n.keywords):  # **kwargs: trusted
            continue
        kws = {k.arg: k.value for k in n.keywords}
        if not any(k in kws and not _is_false(kws[k]) for k in _TEXT_KWS):
            continue
        if _DECODE_KWS & kws.keys():
            continue
        lines.append(n.lineno)
    return lines


def _tree_counts() -> dict[str, int]:
    files = [(relative_posix(p), p) for p in repo_files(REPO_ROOT, ("*.py",))]
    assert len(files) > 200, "the tracked-file walk returned almost nothing"
    out: dict[str, int] = {}
    for rel, path in files:
        if rel.startswith(_OUT_OF_SCOPE) or "/tests/" in rel:
            continue
        try:
            n = len(undecoded_spawns(path.read_text(encoding="utf-8")))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
        if n:
            out[rel] = n
    return out


def test_no_new_text_spawn_without_a_decode_policy():
    counts = _tree_counts()
    over = {f: (n, _BASELINE.get(f, 0)) for f, n in counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, (
        "a text=True subprocess spawn must also pass encoding= and/or errors= (file: found, allowed): "
        f"{over}"
    )


def test_baseline_only_shrinks_and_is_exact():
    counts = _tree_counts()
    stale = sorted(f for f in _BASELINE if counts.get(f, 0) == 0)
    assert not stale, f"_BASELINE rows that no longer offend (drop them): {stale}"
    loose = sorted(f for f, n in _BASELINE.items() if counts.get(f, 0) < n)
    assert not loose, f"_BASELINE counts above the measured count (lower them): {loose}"


def test_scanner_is_live():
    bad = {
        "run text": "import subprocess\nsubprocess.run(['git'], capture_output=True, text=True)",
        "check_output": "import subprocess\nsubprocess.check_output(['x'], text=True)",
        "universal_newlines": "import subprocess\nsubprocess.run(['x'], universal_newlines=True)",
        "alias": "import subprocess as sp\nsp.Popen(['x'], text=True)",
        "bare name": "from subprocess import run\nrun(['x'], text=True)",
        "text from variable": "import subprocess\nsubprocess.run(['x'], text=flag)",
    }
    for label, src in bad.items():
        assert undecoded_spawns(src), f"scanner missed {label}"
    quiet = [
        "import subprocess\nsubprocess.run(['x'], text=True, encoding='utf-8')",
        "import subprocess\nsubprocess.run(['x'], text=True, errors='replace')",
        "import subprocess\nsubprocess.run(['x'], capture_output=True)",
        "import subprocess\nsubprocess.run(['x'], text=False)",
        "import subprocess\nsubprocess.run(['x'], text=True, **kw)",
        "other.run(['x'], text=True)",
    ]
    for src in quiet:
        assert not undecoded_spawns(src), f"scanner flagged a quiet shape: {src}"


def test_scanner_reports_the_call_line():
    src = "import subprocess\nx = 1\nsubprocess.run(\n    ['x'], text=True)\n"
    assert undecoded_spawns(src) == [3]
