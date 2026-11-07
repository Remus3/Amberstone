"""S144-P-286 - a test's docstring or comment never names a removed repo script as if it were live.

Sibling of test_dangling_py_cite_ratchet_s144p273 (production .py) and the doc guards p284 / p285. That guard leaves
``tests/`` out because test BODIES are full of placeholder paths built as fixtures; the prose of a test is a different
surface: a docstring or ``#`` comment that says "the key comes from <path>" or "calls <path>" is a pointer a reader
follows. Measured 2026-11-06 over the tracked ``tests/**/*.py``, docstrings and comments only (string literals in code
are not prose and are not scanned): 21 cites of an untracked ``<top-dir>/<path>.py``. Seven were real stale pointers
and are fixed with this guard (the removed PBE coach and engine in four TFT tests, the removed cooldown dashboard module
in two, one removed TFT script in the orphan-artifact test). The rest are the named placeholders below.

The rule is the p273 rule: an untracked cite needs a history word within three lines, or an entry in ``_ALLOWED``
(file, path) with the reason. ``_ALLOWED`` only shrinks (``test_allowlist_is_exact``). ``test_prose_extractor_is_live``
proves the extractor keeps docstring and comment text and drops code strings, since an empty scan would pass for any
reason.
"""
from __future__ import annotations

import ast
import io
import subprocess
import tokenize

from tests._repo_walk import REPO_ROOT
from tests.test_dangling_py_cite_ratchet_s144p273 import scan_source

# (file, cited path) -> why it is not a dangling pointer. Only shrinks.
_ALLOWED = {
    # Placeholder module names inside a docstring that describes a fixture the test builds in tmp_path.
    ("tests/test_citation_audit_spaced_paths.py", "tools/x.py"),
    ("tests/test_command_doc_script_cites_s144p284.py", "tools/x.py"),
    ("tests/test_cost_trace_matrix_is_live.py", "tools/x.py"),
    ("tests/test_done_md_push_ci_shape.py", "tools/x.py"),
    ("tests/test_md_guard_selector_option_args_s144q41.py", "tools/x.py"),
    ("tests/test_launcher_update_cycle_pkg6b.py", "core/a.py"),
    ("tests/test_launcher_update_hardening_pkg6b.py", "core/a.py"),
    ("tests/test_launcher_update_hardening_pkg6b.py", "core/b.py"),
    # The docstring lists the five scripts it pins as removed; the word "removed" sits in its first lines, more than
    # three apart from the list (S144-P-287: the word "sibling" marked this one before).
    ("tests/test_orphan_scripts_rm227.py", "ops/phase3_summary.py"),
    # The per-session lane drivers are gitignored runtime files the test describes, never tracked.
    ("tests/test_fleet_test_guard_lane_driver_rm874.py", "ops/loop/control/lane_prompts/s133_lane_driver.py"),
    ("tests/test_fleet_test_guard_lane_driver_rm874.py", "ops/loop/control/lane_prompts/s134_lane_driver.py"),
}


def _tracked() -> frozenset[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout
    return frozenset(line for line in out.split("\n") if line)


def _prose(src: str) -> str:
    """``src`` with every line blanked except docstring lines and ``#`` comments (line numbers kept)."""
    lines = [""] * (src.count("\n") + 1)
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            segment = ast.get_source_segment(src, first) or ""
            for offset, text in enumerate(segment.split("\n")):
                lines[first.lineno - 1 + offset] = text
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            lines[tok.start[0] - 1] = tok.string
    return "\n".join(lines)


def _test_files(tracked: frozenset[str]) -> list[str]:
    return sorted(
        p for p in tracked
        if p.startswith("tests/") and p.endswith(".py") and "/guard_data/" not in p
    )


def _tree_hits() -> set[tuple[str, str]]:
    tracked = _tracked()
    found: set[tuple[str, str]] = set()
    for rel in _test_files(tracked):
        try:
            prose = _prose((REPO_ROOT / rel).read_text(encoding="utf-8"))
        except (UnicodeDecodeError, OSError, SyntaxError):
            continue
        for _line, cited in scan_source(prose, tracked):
            found.add((rel, cited))
    return found


def test_test_files_are_enumerated():
    files = _test_files(_tracked())
    assert "tests/test_tft_round_schedule_rm855.py" in files
    assert len(files) >= 500


def test_no_bare_cite_of_a_missing_script_in_test_prose():
    new = sorted(_tree_hits() - _ALLOWED)
    assert not new, (
        "test docstring / comment cites a repo script that is not tracked and carries no history word within "
        f"3 lines (say it was removed, or drop the cite): {new}"
    )


def test_allowlist_is_exact():
    stale = sorted(_ALLOWED - _tree_hits())
    assert not stale, f"_ALLOWED entries that no longer match a bare cite - drop them: {stale}"


def test_prose_extractor_is_live():
    tracked = _tracked()
    src = (
        '"""Module doc cites core/gone_one.py here."""\n'
        "def f():\n"
        '    """The key comes from coaches/gone_two.py."""\n'
        '    x = "tools/gone_three.py"  # see tools/gone_four.py\n'
        "    return x\n"
    )
    cited = [c for _l, c in scan_source(_prose(src), tracked)]
    assert cited == ["core/gone_one.py", "coaches/gone_two.py", "tools/gone_four.py"]
    marked = '"""Used coaches/gone_five.py (removed in an earlier cleanup)."""\n'
    assert scan_source(_prose(marked), tracked) == []
    assert scan_source(_prose('x = "core/gone_six.py"\n'), tracked) == []
