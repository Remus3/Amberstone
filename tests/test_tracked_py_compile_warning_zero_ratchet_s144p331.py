"""S144-P-331 - every tracked .py compiles with no SyntaxWarning, held at zero.

CPython reports a class of real defects only as a compile-time warning, and only when the module is compiled fresh
(a cached .pyc hides it on the next import): an invalid escape sequence in a plain string (a Windows path or a regex
written without ``r""`` - the warning says it will become an error), ``x is 1`` (identity against a literal),
``assert (cond, "msg")`` (a tuple, always true), and on Python 3.14 a ``return`` / ``break`` / ``continue`` that leaves
a ``finally`` block (PEP 765: it silently swallows the in-flight exception). Ruff selects most of these as separate
codes, but only for a file ruff reads; nothing asked the interpreter itself, which is the authority on its own
warnings. The one existing compile-warning check (tests/test_doc_line_cites_in_source_s144p96.py) covers a named
list of modules.

Measured 2026-11-07 on CPython 3.14.4 over every tracked .py (4107 files, tests and vendored kit included, since a
warning in a test module is as much a defect as one in production): 0 warnings, 0 SyntaxErrors. This module holds
that at zero with ``warnings.simplefilter("always")`` and a recorded list, so a warning that a previous import had
already printed once is still seen. A file that does not compile at all is reported too (an unreadable or
non-Python-3 file under a ``.py`` name would otherwise be a silent hole in every AST guard, each of which skips
``SyntaxError``).

A scan is a claim about its own pattern, so ``test_scanner_is_live`` proves each warning shape is reported and a clean
module is quiet. The 3.14-only shape is skipped on an older interpreter, where the compiler does not emit it.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path


from tests._repo_walk import REPO_ROOT, relative_posix, repo_files


def compile_findings(src: bytes | str, name: str = "<src>") -> list[str]:
    """Every warning or error compiling ``src`` raises, as ``"<line> <Category>: <message>"``."""
    found: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            compile(src, name, "exec", dont_inherit=True)
        except SyntaxError as exc:
            found.append(f"{exc.lineno} SyntaxError: {exc.msg}")
        except (ValueError, RecursionError, MemoryError) as exc:
            # defensive: a null byte is a SyntaxError on 3.12+ (ValueError before), and a source nested too deeply
            # for the parser can raise RecursionError / MemoryError - the file does not compile either way.
            found.append(f"0 {type(exc).__name__}: {str(exc)[:60]}")
    for item in caught:
        found.append(f"{item.lineno} {item.category.__name__}: {str(item.message)[:80]}")
    return found


def _tree_findings() -> dict[str, list[str]]:
    files = repo_files(REPO_ROOT, ("*.py",))
    assert len(files) > 1000, f"the tracked-file walk returned only {len(files)} .py files"
    out: dict[str, list[str]] = {}
    for path in files:
        try:
            raw = Path(path).read_bytes()
        except OSError:
            continue
        found = compile_findings(raw, relative_posix(path))
        if found:
            out[relative_posix(path)] = found
    return out


def test_no_tracked_py_compiles_with_a_warning_or_an_error():
    findings = _tree_findings()
    assert not findings, (
        "tracked .py files that raise a compile-time warning or error (fix the source: use a raw string for a "
        f"backslash, == for a literal, no return / break / continue out of finally): {findings}"
    )


def test_scanner_is_live():
    bad = {
        "invalid escape": 'x = "C:\\data\\new_dir\\d"\n',
        "is with a literal": "def f(x):\n    return x is 1\n",
        "assert on a tuple": "def f(x):\n    assert (x, 'message')\n",
        "syntax error": "def f(:\n",
        "null byte": b"x = 1\x00\n",
    }
    for label, src in bad.items():
        assert compile_findings(src), f"scanner missed {label}"


def test_scanner_reports_a_return_out_of_finally():
    """PEP 765: the interpreter warns on a return out of finally only from 3.14, so the scanner reports it there
    and stays quiet before (hosted CI runs 3.12). A version branch, not a skip: a skip gated on the interpreter
    version is not a capability tests/test_skip_condition_hygiene.py can resolve, and this runs on both."""
    src = "def f():\n    try:\n        pass\n    finally:\n        return 1\n"
    if sys.version_info >= (3, 14):
        assert compile_findings(src), "scanner missed return in finally"
    else:
        assert not compile_findings(src), "a pre-3.14 compile does not warn on return in finally"


def test_scanner_is_quiet_on_clean_source():
    good = [
        "x = 1\n",
        'p = r"C:\\data\\new_dir"\n',
        'p = "C:\\\\data\\\\new"\n',
        "def f(x):\n    return x == 1\n",
        "def f(x):\n    assert x, 'message'\n",
        "def f():\n    try:\n        return 1\n    finally:\n        pass\n",
        "async def g():\n    return [i async for i in h()]\n",
    ]
    for src in good:
        assert compile_findings(src) == [], f"false positive on {src!r}: {compile_findings(src)}"


def test_scanner_reaches_known_files():
    names = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for anchor in ("web_dashboard.py", "core/build_order.py", "tests/_repo_walk.py"):
        assert anchor in names, f"the walk no longer reaches {anchor}"
