"""G004 - no production logging call builds its message with an f-string (S144-P-495).

``logger.info(f"... {x}")`` formats the message whether or not the level is enabled and hands the
logging machinery a finished string, so a handler or filter cannot group by the template. The lazy
``logger.info("... %s", x)`` form is the stdlib's own: the arguments are merged by
``LogRecord.getMessage()`` only when a handler emits the record, and every consumer that reads
``record.getMessage()`` (``caplog``, the RC log scrubber) sees the same text. ruff.toml does not
select G004 and no earlier ratchet covers it. Measured 2026-11-09 with ``ruff check --isolated``
(target py39) over the tracked production tree: 51 findings in 6 files. This slice converts the
16 sites in the four ``core/`` modules no lane branch touches (the three precompute generators'
``main()`` banners and the aftergame CLI); the 35 in ``tools/lcu_agent.py`` followed in S144-P-499
(that file is a long-running agent with many call sites: a slice of its own), so the baseline is
now empty and stays a dict that only shrinks. A baseline row that stops offending fails
``test_baseline_is_exact`` until it is dropped; a new finding anywhere fails
``test_no_new_findings``.

``agents/daemon_slayer/cli.py`` (8 more, the only DS module with a finding; no lane branch touched
it) followed in S144-P-505 and the DS package is now in scope.

Scope: tracked ``.py`` files. ``tests/``, any ``*/tests/`` directory (so the DS test tree too), the
vendored ``ops/fleet_kit`` and the ``agents/agent3_testing/suite`` suite are out of scope. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide
a finding.
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

_RULE = "G004"
_OUT_OF_SCOPE = (
    "tests/",
    "tools/tests/",
    "agents/agent3_testing/suite/",
    "ops/fleet_kit/",
)
# file -> finding count that stays. Only shrinks; empty since S144-P-499.
_BASELINE: dict[str, int] = {}
_FIXED = (
    "agents/daemon_slayer/cli.py",
    "core/aftergame_summary.py",
    "core/build_order_precompute.py",
    "core/build_order_variants.py",
    "core/laning_scenario_precompute.py",
    "tools/lcu_agent.py",
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


def test_probe_is_live():
    """The isolated run reports a minimal offender, so an empty tree result is a real scan."""
    probe = "import logging\nlog = logging.getLogger('x')\nlog.info(f'a {1}')\n"
    found = _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert _RULE in {d["code"] for d in found}
    ok = "import logging\nlog = logging.getLogger('x')\nlog.info('a %s', 1)\n"
    assert not _ruff(["--select", _RULE, "--stdin-filename", "probe_mod.py", "-"], stdin=ok)
