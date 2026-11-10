"""RM-1412 - ten ruff rules that flag a dead branch, a muddy precedence or a
broken dunder are held at zero.

None of these is selected by ruff.toml. Measured 2026-11-04 with
``ruff check --isolated`` over the tree, 13 sites in 11 files, all fixed:

- RUF034 (a conditional whose two arms are equal): ops/loop/repo_review.py had
  ``depth = 4 if cid == "ddragon-web" else 4``.
- RUF021 (``a or b and c`` without parentheses): core/build_planner/planner.py.
  The parse was already ``a or (b and c)``; the parentheses state it.
- RUF051 (``in`` check then ``del``): agents/agent1_lead/scheduler.py.
- PLC0208 (iterating a set literal): composition_advisor.py.
- PLR0133 / PLE0307 / PLW0406 / RUF019 / RUF017 / SIM201: seven test files
  (a constant-vs-constant comparison, a ``__str__`` returning a literal int, a
  module importing itself, a redundant key check, quadratic ``sum(..., [])``,
  ``not v == v``).

Left out on purpose: PLC3002 (one lambda call in the DS effects data, the DS
lane's file), ISC001 (frozen ops/rc_supervisor.py), and the style-only rules
(RSE102, RUF010) that would only churn files.

The ratchet runs ruff with NO config (``--isolated``) so a per-file-ignore cannot
hide a finding, and keeps only tracked files. Zero is the baseline.
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

_RULES = "RUF034,RUF021,RUF019,RUF051,RUF017,PLR0133,PLW0406,PLC0208,PLE,SIM201"
_FIXED = (
    "agents/agent1_lead/scheduler.py",
    "composition_advisor.py",
    "core/build_planner/planner.py",
    "ops/loop/repo_review.py",
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


@pytest.fixture(scope="module")
def tree_findings() -> list[str]:
    # The whole tree on one command line is too long for Windows: lint ".", keep
    # the tracked files (the filter the other ruff ratchets use).
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    out = []
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            out.append(f"{rel}:{d['location']['row']} {d['code']}")
    return sorted(out)


def test_tree_carries_no_dead_branch_or_precedence_finding(tree_findings):
    assert not tree_findings, f"ruff {_RULES}: {tree_findings}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


def test_the_repo_review_depth_is_a_plain_constant():
    src = (REPO_ROOT / "ops/loop/repo_review.py").read_text(encoding="ascii")
    assert "        depth = 4\n" in src
    assert 'depth = 4 if' not in src


def test_the_planner_condition_keeps_its_meaning():
    """``not seed or (not ranked and not order)`` - the parenthesised form is the
    parse the unparenthesised one always had."""
    src = (REPO_ROOT / "core/build_planner/planner.py").read_text(encoding="ascii")
    assert 'if not seed or (not seed.get("ranked") and not seed.get("order")):' in src


@pytest.mark.parametrize(
    "code, expected",
    [
        ("x = 4 if c else 4\n", "RUF034"),
        ("if a or b and c:\n    pass\n", "RUF021"),
        ("d = {}\nif 'k' in d:\n    del d['k']\n", "RUF051"),
        ("for m in {'a', 'b'}:\n    print(m)\n", "PLC0208"),
        ("assert 'a' > 'b'\n", "PLR0133"),
        ("class E(Exception):\n    def __str__(self):\n        return 5\n", "PLE0307"),
        ("def f(v):\n    return not v == v\n", "SIM201"),
        ("x = sum([[1], [2]], [])\n", "RUF017"),
        ("d = {}\nif 'k' in d and d['k']:\n    pass\n", "RUF019"),
    ],
)
def test_each_probe_is_live(code, expected):
    """Every rule in the set IS reported by the isolated run on a minimal
    offender - so an empty tree result is a clean tree, not a dead probe."""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=code)
    assert expected in {d["code"] for d in found}, found
