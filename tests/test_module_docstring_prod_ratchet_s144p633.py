"""D100 / D104 - a production module and a production package carry a docstring (S144-P-633).

ruff.toml does not select D100 (missing module docstring) or D104 (missing package docstring) and no
earlier ratchet covers them. Five production packages (``core``, ``modes``, ``modules``, ``ops``,
``ops/audit``) had an empty or comment-only ``__init__.py``; each now states in one line what the
package holds, so ``help(core)`` and an outsider reading the tree learn something. The change is a
string expression statement at the top of the file: the import behaviour is unchanged (checked by
``test_package_docstring_is_set``).

One baseline row stays: ``core/safe_coach_output.py`` (another lane branch changed it, so this lane
leaves it; the merger or the owning lane adds the docstring and drops the row). The row can only
shrink: a file that reaches zero must leave ``_BASELINE``, and a new finding anywhere fails.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory and the vendored ``ops/fleet_kit``
are out of scope (the test-side findings are a separate slice). The run uses NO config
(``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
import importlib
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

_RULES = "D100,D104"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (module docstring). Only shrinks.
_BASELINE = {
    "core/safe_coach_output.py": 1,
}
_FIXED_PACKAGES = (
    "core",
    "modes",
    "modules",
    "ops",
    "ops.audit",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin,
        check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", _RULES, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("pkg", _FIXED_PACKAGES)
def test_package_docstring_is_set(pkg):
    init = REPO_ROOT.joinpath(*pkg.split(".")) / "__init__.py"
    assert init.is_file(), f"{init} missing - update _FIXED_PACKAGES"
    assert relative_posix(init) not in {f for f in _BASELINE}
    mod = importlib.import_module(pkg)
    assert isinstance(mod.__doc__, str)
    assert mod.__doc__.strip(), f"{pkg} has an empty docstring"
    assert "\n" not in mod.__doc__.strip(), f"{pkg} docstring is meant to be one line"


def test_probe_is_live():
    """The isolated run reports minimal offenders, so an empty tree result is a real scan."""
    bad_mod = "x = 1\n"
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=bad_mod)
    assert "D100" in {d["code"] for d in found}
    bad_pkg = ""
    found = _ruff(["--select", _RULES, "--stdin-filename", "probe_pkg/__init__.py", "-"], stdin=bad_pkg)
    assert "D104" in {d["code"] for d in found}
    ok = '"""One line."""\nx = 1\n'
    assert not _ruff(["--select", _RULES, "--stdin-filename", "probe_mod.py", "-"], stdin=ok)
