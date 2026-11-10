"""RM-1416 - three ruff rules are held at zero outside one frozen file.

None of these is selected by ruff.toml. Measured 2026-11-05 with
``ruff check --isolated`` over the tree: 9 sites in 5 files. 8 are fixed by this
slice; the ninth is in the frozen app/_loop.py and is the only entry in
``_FROZEN_WAIVED``, so any other new site fails.

- PLW0602 ``global X`` in a function that never assigns X: the statement is a
  no-op that reads as a rebind. Mutating through the name (``.append``,
  item assignment) needs no ``global``.
- RET502 a bare ``return`` in a function whose other returns carry a value: say
  ``return None`` so the missing value reads as deliberate.
- PERF101 ``for x in list(it)``: the cast copies for nothing. hotkeys.py
  snapshots with ``tuple(...)`` instead, because the copy is deliberate there
  (register_coach may append while the loop runs on another thread).

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore
cannot hide a finding, and keeps only tracked files.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests._repo_walk import REPO_ROOT, relative_posix, repo_files

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None,
    reason="ruff is not importable by this interpreter",
)

_RULES = "PLW0602,RET502,PERF101"
# Frozen (CLAUDE.md): app/_loop.py:44 `global _INSTANCE` is a PLW0602 site.
# Reverses if: the operator approves an edit to app/_loop.py - then drop this.
_FROZEN_WAIVED = {("app/_loop.py", "PLW0602")}
_FIXED = (
    "agents/_supervisor_http.py",
    "core/hotkeys.py",
    "dashboard/routes_team_context.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def test_tree_has_no_new_global_return_or_cast_finding():
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    found = []
    seen_waived = set()
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel not in tracked:
            continue
        if (rel, d["code"]) in _FROZEN_WAIVED:
            seen_waived.add((rel, d["code"]))
            continue
        found.append(f"{rel}:{d['location']['row']} {d['code']}")
    assert not found, f"ruff {_RULES}: {found}"
    # A waiver for a site that no longer exists is stale: drop it.
    assert seen_waived == _FROZEN_WAIVED, f"stale waiver: {_FROZEN_WAIVED - seen_waived}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_hotkeys_snapshots_the_coach_list_before_iterating():
    """The PERF101 fix must keep a copy: dropping it would let a concurrent
    register_coach append during the loop."""
    src = (REPO_ROOT / "core" / "hotkeys.py").read_text(encoding="ascii")
    assert "for coach in tuple(_coaches):" in src


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("X = []\n\n\ndef f():\n    global X\n    X.append(1)\n", "PLW0602"),
        ("def f(a):\n    if a:\n        return\n    return 1\n", "RET502"),
        ("for v in list([1, 2]):\n    print(v)\n", "PERF101"),
    ],
)
def test_each_probe_is_live(code, expected):
    """Each rule flags a minimal offender - so an empty tree result is a clean
    tree, not a dead probe."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=code)
    assert expected in {d["code"] for d in found}, found
