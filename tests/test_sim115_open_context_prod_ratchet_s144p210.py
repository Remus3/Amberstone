"""RM-1718 - ruff SIM115 (open() without a context manager) held in production code.

ruff.toml selects SIM115 nowhere and no earlier ratchet covers it. Measured 2026-11-06 with
``ruff check --isolated`` (target py39): production code carried 33 findings in 13 files. Thirty-two are
fixed: one-shot ``json.load(open(p))`` / ``open(p).read()`` reads and ``json.dump(x, open(p, "w"))`` /
``open(p, "w").write(s)`` writes in the audit and DS prefilter scripts now read through ``Path.read_text`` or
write inside a ``with`` block, so the handle is closed (and a write flushed) on the line that used it
instead of whenever the interpreter collects it. Bytes written are unchanged (the LF writes keep ``newline``).

The one finding that stayed (``core/live_session_recorder.py`` ``_repair_torn_tail``, an ``r+b`` open inside a ``try``
that maps FileNotFoundError to "nothing to repair", then ``with fh:``) is gone: S144-P-567 spelled it
``path.open("r+b")``, which SIM115 does not flag, so the baseline is empty and the file joins ``_FIXED``. A baseline row that stops offending fails ``test_baseline_is_exact`` until it is dropped; a
new finding anywhere else fails ``test_no_new_findings``.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the vendored
``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope. The run uses NO config
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

_RULE = "SIM115"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reason in the module docstring). Only shrinks; empty since S144-P-567.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "ops/audit/lolmath_ds_sweep/g2_remeasure_probe.py",
    "ops/audit/lolmath_ds_sweep/g7_comp_harness.py",
    "ops/audit/lolmath_ds_sweep/gen_md.py",
    "ops/audit/opponent_prior_gonogo.py",
    "ops/audit/p2w5_partition.py",
    "ops/audit/p2w5h2_partition.py",
    "ops/audit/p3c24_token_equiv.py",
    "tools/ds_cc_conditional_to_json.py",
    "tools/ds_cond_inspect.py",
    "tools/ds_cond_pair_prefilter.py",
    "tools/ds_execute_prefilter.py",
    "tools/p3_ascii_census.py",
    "core/live_session_recorder.py",
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
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len(tracked) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["--select", _RULE, "."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and not rel.startswith(_OUT_OF_SCOPE) and "/tests/" not in rel:
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULE} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    """A baseline row that no longer offends (or offends less) must shrink or go."""
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert (REPO_ROOT / rel).is_file(), f"{rel} missing - update _FIXED"
    assert rel not in tree_counts


@pytest.mark.parametrize(
    "probe",
    [
        'import json\nd = json.load(open("x.json", encoding="utf-8"))\n',
        'open("x.txt", "w").write("a")\n',
    ],
)
def test_probe_is_live(probe):
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert _RULE in {d["code"] for d in found}
