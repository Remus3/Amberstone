"""RM-1695 - A001 held at zero outside the vendored kit; SIM110, PERF402 and PERF403 held in the test code.

None of these rules is selected by ruff.toml, and the earlier production ratchets (S144-P-146 PERF403, S144-P-148
SIM110, RM-1527 PERF402) keep ``tests/``, ``*/tests/`` and ``agents/agent3_testing/suite`` out of scope. Measured
2026-11-05 with ``ruff check --isolated`` (target py39, line length 120 so SIM110 reports only a rewrite that fits):

- A001 (variable shadows a builtin): ``tools/build_third_party_notices.py`` bound a local named ``credits``;
  it is ``credits_file`` now. ``ops/fleet_kit/fleet_headless.py`` (``input``) is vendored byte-for-byte, so that
  file is out of scope, as it is in every other ratchet. The rule is checked over the whole tree outside the kit.
- SIM110: ``tests/test_aram_vision_cadence_fastpoll.py`` looped ``if not any(...): return False`` over the grid
  starts; it is ``return all(any(...) for w in starts)`` now (same truth table, same short-circuit).
- PERF403: ``tests/test_no_process_wide_stdlib_fakes_rm801.py`` filled ``out[name] = term`` in a conditional loop;
  it is ``out.update({...})`` now (same keys, same values, same order).
- PERF402: ``tests/test_collection_idiom_ratchet_s144p141.py`` keeps ONE append loop on purpose: it is the
  "before" half of an equivalence assertion (``looped`` vs ``ext.extend``), so rewriting it would erase the thing
  the assertion compares. That row is the baseline and it only shrinks.

Out of scope for the test-code rules: ``agents/daemon_slayer/`` (the ds lane's package; one PERF403 in
``agents/daemon_slayer/tests/test_stranded_hsp_seam_r197.py`` is a filing). The run uses NO config
(``--isolated``) so a per-file-ignore cannot hide a finding.
"""
from __future__ import annotations

import collections
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

_TREE_RULES = ("A001",)
_TEST_RULES = ("SIM110", "PERF402", "PERF403")
_KIT = "ops/fleet_kit/"
_DS = "agents/daemon_slayer/"
# file -> finding count that stays (reason in the module docstring). Only shrinks.
_BASELINE = {
    "tests/test_collection_idiom_ratchet_s144p141.py": 1,
}
_FIXED = (
    "tests/test_aram_vision_cadence_fastpoll.py",
    "tests/test_no_process_wide_stdlib_fakes_rm801.py",
    "tools/build_third_party_notices.py",
)


def _is_test_code(rel: str) -> bool:
    return (rel.startswith(("tests/", "agents/agent3_testing/suite/"))
            or "/tests/" in rel) and not rel.startswith(_DS)


def _ruff(rules: tuple[str, ...], args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(rules), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


def _counts(rules: tuple[str, ...], keep) -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(rules, ["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and keep(rel):
            counts[rel] += 1
    return dict(counts)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    return _counts(_TREE_RULES, lambda rel: not rel.startswith(_KIT))


@pytest.fixture(scope="module")
def test_code_counts() -> dict[str, int]:
    return _counts(_TEST_RULES, _is_test_code)


def test_no_builtin_shadowing_variable_outside_the_kit(tree_counts):
    assert not tree_counts, f"ruff A001 findings, file: count: {tree_counts}"


def test_no_new_test_code_findings(test_code_counts):
    extra = {f: n for f, n in test_code_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {'/'.join(_TEST_RULES)} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(test_code_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if test_code_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


_PROBES = {
    "A001": "def f():\n    credits = 1\n    return credits\n",
    "SIM110": "def f(xs):\n    for x in xs:\n        if x > 1:\n            return True\n    return False\n",
    "PERF402": "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n",
    "PERF403": "def f(d):\n    out = {}\n    for k, v in d.items():\n        if v:\n            out[k] = v\n    return out\n",
}


def test_every_rule_has_a_probe():
    assert set(_PROBES) == set(_TREE_RULES) | set(_TEST_RULES)


@pytest.mark.parametrize("rule", sorted(_PROBES))
def test_probe_is_live(rule):
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff((rule,), ["--stdin-filename", "probe_mod.py", "-"], stdin=_PROBES[rule])
    assert {d["code"] for d in found} == {rule}


def test_the_kit_exemption_is_real():
    """A001 still fires in the vendored kit; only the scope hides it. If the kit stops offending, drop _KIT."""
    found = _ruff(_TREE_RULES, ["ops/fleet_kit"])
    assert found, "ops/fleet_kit no longer has an A001 finding: drop the _KIT exemption"


def test_the_ds_test_exemption_is_real():
    found = _ruff(_TEST_RULES, ["agents/daemon_slayer/tests"])
    assert found, "agents/daemon_slayer/tests no longer has a finding: drop the _DS exemption"


def test_fixed_semantics_are_unchanged():
    from tests.test_aram_vision_cadence_fastpoll import _covers_every_window

    assert _covers_every_window([0.0, 3.0, 6.0], search_end=3.0, window=3.0)
    assert not _covers_every_window([0.0], search_end=3.0, window=1.0)
