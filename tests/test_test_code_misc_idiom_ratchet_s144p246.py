"""RM-1746 - ruff SIM112, SIM114, FURB171, D200 and PERF402 held at zero in test code.

Not selected by ruff.toml. Measured 2026-11-06 with ``ruff check --isolated`` (target py39) over the tracked
``tests/`` and ``tools/tests/`` code: 13 findings in 11 modules, 11 fixed in this slice (the other 2 are the baseline below):

- SIM112 (9, 7 fixed): ``os.environ.get("SystemRoot")`` in six modules now says ``SYSTEMROOT``, the key ``os.environ``
  stores (Windows upper-cases it; any other OS read nothing). ``tests/test_kit_v10_spawn_routes.py`` dropped the
  now-redundant ``or os.environ.get("SYSTEMROOT")`` fallback.
- SIM114 (1): the two identical ``os.truncate`` / ``os.remove`` branches of the audit hook in ``tests/conftest.py``
  are one ``event in (...)`` branch.
- FURB171 (1): ``sink not in (sys.__stdout__,)`` is ``sink is not sys.__stdout__`` (identity is the intent).
- D200 (1): a one-line class docstring in ``tests/test_laning_scenario_precompute.py`` fits on one line.
- PERF402 (1): the copy loop in ``test_collection_idiom_ratchet_s144p141`` is the premise under test, so it carries
  a reasoned ``noqa``.

Baseline: two SIM112 reads in ``tests/test_launcher_key_read_rm810.py``, a PKG-owned module the lanes may not edit
(tests/test_launcher_* is excluded). Out of scope: ``agents/daemon_slayer/`` tests (two D200 and one PERF403 rows,
the DS lane's). The run uses NO config (``--isolated``), so a per-file-ignore cannot hide a finding. The baseline only
shrinks.
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

_RULES = ("SIM112", "SIM114", "FURB171", "D200", "PERF402")
_IN_SCOPE = ("tests/", "tools/tests/")
_BASELINE: dict[str, int] = {"tests/test_launcher_key_read_rm810.py": 2}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", ",".join(_RULES), *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def tree_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    assert len([t for t in tracked if t.startswith("tests/")]) > 100, "the tracked-file walk returned almost nothing"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["tests", "tools/tests"]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked and rel.startswith(_IN_SCOPE):
            counts[rel] += 1
    return dict(counts)


def test_no_new_findings(tree_counts):
    extra = {f: n for f, n in tree_counts.items() if n > _BASELINE.get(f, 0)}
    assert not extra, f"ruff {_RULES} findings beyond the baseline, file: count: {extra}"


def test_baseline_is_exact(tree_counts):
    stale = {f: n for f, n in _BASELINE.items() if tree_counts.get(f, 0) != n}
    assert not stale, f"baseline rows to shrink or drop (file: recorded): {stale}"


@pytest.mark.parametrize(
    ("rule", "probe"),
    [
        ("SIM112", "import os\nx = os.environ.get('SystemRoot')\n"),
        ("SIM114", "def f(e):\n    if e == 1:\n        return 1\n    elif e == 2:\n        return 1\n    return 0\n"),
        ("FURB171", "def f(s):\n    return s in (1,)\n"),
        ("D200", 'def f():\n    """\n    One line.\n    """\n'),
        ("PERF402", "def f(src):\n    out = []\n    for x in src:\n        out.append(x)\n    return out\n"),
    ],
)
def test_probe_is_live(rule, probe):
    """The isolated run reports a minimal offender per rule, so an empty tree result is a real scan."""
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=probe)
    assert any(d["code"] == rule for d in found), (rule, [d["code"] for d in found])


def test_the_fixed_reads_say_the_stored_key():
    """The six SystemRoot readers spell the key os.environ stores, not the mixed-case form."""
    fixed = (
        "tests/test_batch_embed_stamp_gate_a45b.py",
        "tests/test_batch_system_tools_rm826.py",
        "tests/test_install_startup_shortcut_rm826.py",
        "tests/test_kit_v10_spawn_routes.py",
        "tests/test_phase3_setup_rerun_bytes_rm820.py",
        "tests/test_voice_coach_ps_injection.py",
    )
    for rel in fixed:
        src = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert 'os.environ.get("SYSTEMROOT"' in src, rel
        assert 'os.environ.get("SystemRoot"' not in src, rel
