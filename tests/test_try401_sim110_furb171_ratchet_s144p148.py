"""RM-1534 - TRY401, SIM110 and FURB171 are held at a baseline that only shrinks.

None of the three rules is selected by ruff.toml. Measured 2026-11-05 with ``ruff check --isolated``
(target py39): production code carried 4 TRY401, 2 SIM110 and 1 FURB171 site.

- TRY401: ``logger.exception("...: %s", e)`` repeats the exception text the logging module already
  appends as the traceback. Three handlers (the file-ingest tick loop, the per-mode pipeline refresh and
  the coach loop) now log the context only; the traceback still carries the exception.
- SIM110: ``core/hot_reload._should_watch`` and ``tools/stop_claim_gate._bypass_hits_rc`` each looped to
  return True on the first hit; both now return ``any(...)`` over the same generator (lazy, so the
  short-circuit and the evaluation order are unchanged).
- FURB171: ``tools/ds_cross_eval/probe_champion`` tested ``x in ("burst",)``; it is ``x == "burst"``.

``tools/upstream_drift_check.py`` was held by another lane branch at the time of this slice (its
redirect-refusal work), so its one TRY401 stayed baselined; S144-P-537 took it (its ``main()`` now logs
``logger.exception("upstream_drift_check hard error")``, the traceback carries the exception) and the baseline is
empty: the three rules are held at zero.

A baseline entry that stops offending fails ``test_baseline_is_exact`` until it is dropped; a new finding
anywhere fails ``test_no_new_findings``.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory, ``agents/daemon_slayer``, the vendored
``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope. The run uses NO config
(``--isolated``, with ruff.toml's line-length 120 passed by hand: SIM110 only reports a rewrite that fits the
line length) so a per-file-ignore cannot hide a finding.
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

_RULES = "TRY401,SIM110,FURB171"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/daemon_slayer/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays (reasons in the module docstring). Empty since S144-P-537.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "agents/agent2_backend/file_ingest.py",
    "agents/agent2_backend/pipeline/orchestrator.py",
    "coach_integration/_coach.py",
    "core/hot_reload.py",
    "tools/ds_cross_eval/probe_champion.py",
    "tools/stop_claim_gate.py",
    "tools/upstream_drift_check.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120",
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


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_is_ascii_and_lf(rel):
    raw = (REPO_ROOT / rel).read_bytes()
    raw.decode("ascii")
    assert b"\r" not in raw


@pytest.mark.parametrize("rel", _FIXED)
def test_fixed_module_stays_clean(rel, tree_counts):
    assert rel not in tree_counts


def test_probe_is_live():
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    probes = {
        "TRY401": (
            "import logging\nlog = logging.getLogger('p')\n\n\ndef f():\n    try:\n        pass\n"
            "    except Exception as e:\n        log.exception('boom: %s', e)\n"
        ),
        "SIM110": "def f(xs):\n    for x in xs:\n        if x > 1:\n            return True\n    return False\n",
        "FURB171": "def f(x):\n    return x in ('burst',)\n",
    }
    for code, probe in probes.items():
        found = _ruff(["--select", code, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
        assert {d["code"] for d in found} == {code}, code
