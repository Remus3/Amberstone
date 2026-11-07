"""S144-P-302 - a production subprocess that waits on a child names a timeout.

``subprocess.run`` / ``check_output`` / ``check_call`` / ``call`` default to NO timeout: a child
that wedges (a git index.lock held by another process, a stuck credential helper, a hung ``gh``)
parks the caller forever, and in a git hook or a ``pythonw.exe`` agent that is a silent hang.
Sibling of the S144-P-301 network-open guard.

Measured 2026-11-06 over every tracked ``.py`` (AST, not grep): 231 such calls in 149 files, 200 of
them in tests (out of scope here - a test run is bounded by ``--timeout``) and 31 production calls
in 26 files, one of them in the vendored kit. Ten files (12 calls) that only ask git a short
question (``ls-files`` / ``config`` / ``status`` / ``diff --cached``) now pass ``timeout=`` and left
the baseline. The other 18 calls in 15 files stay in ``_BASELINE`` (file -> unbounded-call count):
each is a build / packaging step that is legitimately long, a one-shot audit script, PKG-owned, or
a path (``sibling_name_sweep``, ``truth_gate``) whose timeout needs its own test. The baseline only
shrinks: a new file, or a file whose count rises, fails; an entry that stops offending fails until
it is dropped.

Stated limits: only the literal ``subprocess.<fn>(...)`` shape is seen (an ``import subprocess as
x`` alias or ``from subprocess import run`` is not; none unbounded exists today), ``Popen`` is not
covered, and ``**kwargs`` is trusted.

``ops/fleet_kit/`` is the vendored kit (byte-pinned, never edited here) and is not scanned.
A call is bounded when it passes ``timeout=`` (any value but a literal ``None``) or splats
``**kwargs`` (the guard cannot see inside, so it does not guess).
"""
from __future__ import annotations

import ast

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

_FUNCS = frozenset({"run", "check_output", "check_call", "call"})

_BASELINE = {
    "ops/audit/p0_inventory.py": 1,
    "ops/audit/p3c23_token_equiv.py": 2,
    "ops/audit/p3c24_token_equiv.py": 1,
    "ops/migrate/e_move_helpers.py": 1,
    "tools/build_installer.py": 1,
    "tools/build_python_embed.py": 1,
    "tools/credential_history_scan.py": 1,
    "tools/dev_cli.py": 1,
    "tools/gated_tft_live_keys.py": 1,
    "tools/package_portable.py": 1,
    "tools/perseus_sync.py": 1,
    "tools/rewrite_sha_citations.py": 1,
    "tools/run_packaged_smoke.py": 1,
    "tools/sibling_name_sweep.py": 1,
    "tools/truth_gate.py": 3,
}


def unbounded_subprocess_calls(source: str) -> list[tuple[int, str]]:
    """(line, ``subprocess.<fn>``) of every wait-on-child call in ``source`` with no timeout."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        fn = node.func
        if not (fn.attr in _FUNCS and isinstance(fn.value, ast.Name) and fn.value.id == "subprocess"):
            continue
        if any(k.arg is None for k in node.keywords):
            continue  # **kwargs may carry it
        explicit = [k for k in node.keywords if k.arg == "timeout"]
        if explicit:
            value = explicit[0].value
            if isinstance(value, ast.Constant) and value.value is None:
                out.append((node.lineno, f"subprocess.{fn.attr}(timeout=None)"))
            continue
        out.append((node.lineno, f"subprocess.{fn.attr}"))
    return out


def _in_scope(rel: str) -> bool:
    if not rel.endswith(".py"):
        return False
    parts = rel.split("/")
    return not (parts[0] == "tests" or "tests" in parts[:-1] or rel.startswith("ops/fleet_kit/"))


def _measure() -> dict[str, list[tuple[int, str]]]:
    found: dict[str, list[tuple[int, str]]] = {}
    for path in repo_files():
        rel = relative_posix(path)
        if not _in_scope(rel):
            continue
        hits = unbounded_subprocess_calls((REPO_ROOT / rel).read_text(encoding="utf-8"))
        if hits:
            found[rel] = hits
    return found


def test_no_new_unbounded_subprocess_in_production():
    found = _measure()
    bad = {
        rel: hits for rel, hits in found.items()
        if len(hits) > _BASELINE.get(rel, 0)
    }
    assert not bad, (
        "production subprocess call(s) with no timeout= (add one, or if the child is legitimately "
        f"long, baseline the file with a reason): {bad}"
    )


def test_baseline_is_exact():
    found = _measure()
    stale = {
        rel: (want, len(found.get(rel, ())))
        for rel, want in _BASELINE.items()
        if len(found.get(rel, ())) != want
    }
    assert not stale, f"baseline row no longer matches (file: (baseline, measured)); shrink it: {stale}"


def test_scanner_flags_the_unbounded_shapes():
    src = (
        "import subprocess\n"
        "subprocess.run(['git', 'status'])\n"
        "subprocess.check_output(['git', 'x'], text=True)\n"
        "subprocess.run(['a'], timeout=None)\n"
    )
    assert [n for _, n in unbounded_subprocess_calls(src)] == [
        "subprocess.run", "subprocess.check_output", "subprocess.run(timeout=None)",
    ]


def test_scanner_passes_bounded_shapes():
    src = (
        "import subprocess\n"
        "subprocess.run(['a'], timeout=30)\n"
        "subprocess.run(['a'], **kw)\n"
        "subprocess.Popen(['a'])\n"
        "other.run(['a'])\n"
    )
    assert unbounded_subprocess_calls(src) == []


def test_scope_skips_tests_and_the_kit():
    assert _in_scope("tools/x.py")
    assert _in_scope("scripts/x.py")
    assert not _in_scope("tests/test_x.py")
    assert not _in_scope("agents/daemon_slayer/tests/test_x.py")
    assert not _in_scope("ops/fleet_kit/fleet_rewrite.py")
    assert not _in_scope("tools/x.md")
