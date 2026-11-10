"""S144-P-653 - ruff N801 (a class name that is not CapWords) is held at zero bar three named files.

N801 is not selected by ruff.toml. Measured 2026-11-10 with ``ruff check --isolated --line-length 120`` (target py39)
over the tracked Python: 22 findings in 10 files. Nineteen are now gone: the 17 unittest classes named
``Phase599_<nn><Suffix>`` in three Daemon Slayer test modules became ``Phase599P<nn><Suffix>`` and the two
``_patch`` context-manager helper classes in the vision test modules became ``_Patch``. Every renamed class is
referenced only inside its own module (grep over the tracked tree, 2026-11-10), so the ``ast.dump`` of each touched
module differs only in those identifiers.

Three files stay named in ``_BASELINE``, each with its reason:

- ``core/resource_manager.py``: ``PROCESS_MEMORY_COUNTERS`` mirrors the Win32 struct of the same name field for field.
- ``agents/daemon_slayer/tests/test_engine_robustness_p1l12.py`` and ``.../test_wireable_sims_p1l3.py``: the ``XXX_`` /
  ``ZZZ_`` prefix is the deliberate first / last sort key of a flagged-gaps class and is cited by that spelling in
  prose (the module's own docstring, plus ``test_ehp_sustain_contract.py`` for the ``ZZZ_`` one), so a rename is a
  prose change as well.

The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding. The baseline only shrinks.
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

_RULES = ("N801",)
# The baseline only shrinks: a new finding fails, and an entry that stops offending fails test_baseline_is_exact.
_BASELINE = {
    "core/resource_manager.py",
    "agents/daemon_slayer/tests/test_engine_robustness_p1l12.py",
    "agents/daemon_slayer/tests/test_wireable_sims_p1l3.py",
}


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--target-version", "py39",
         "--line-length", "120", "--no-fix", "--no-cache", "--output-format", "json",
         "--select", ",".join(_RULES), *args],
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
    for d in _ruff(["."]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in tracked:
            counts[rel] += 1
    return dict(counts)


def test_no_new_n801_finding(tree_counts):
    new = {rel: n for rel, n in tree_counts.items() if rel not in _BASELINE}
    assert not new, f"ruff {_RULES} findings, file: count: {new}"


def test_baseline_is_exact(tree_counts):
    """Every baseline entry still offends; one that no longer does must be dropped (the set only shrinks)."""
    assert not _BASELINE - set(tree_counts), sorted(_BASELINE - set(tree_counts))


def test_renamed_classes_exist_under_their_new_names():
    """The rename is real, not a suppression: the new spellings are defined where the old ones were."""
    def text(rel: str) -> str:
        return (REPO_ROOT / rel).read_text(encoding="utf-8")

    assert "class Phase599P18ExpansionTests(" in text("agents/daemon_slayer/tests/test_block_index_overrides.py")
    assert "class Phase599P21RegistrySeedTests(" in text("agents/daemon_slayer/tests/test_sum_of_blocks_expansion_s215.py")
    assert "class Phase599P22EngineVersionTests(" in text("agents/daemon_slayer/tests/test_sum_of_blocks_expansion_s217.py")
    assert "class _Patch:" in text("tests/test_vision_calibrator_profile.py")
    assert "class _Patch:" in text("tests/test_vision_reference_states.py")


def test_probe_is_live():
    """N801 reports a non-CapWords class name and stays quiet on CapWords."""
    bad = "class Phase_one:\n    pass\n"
    good = "class PhaseOne:\n    pass\n"
    found = _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=bad)
    assert {d["code"] for d in found} == set(_RULES), found
    assert _ruff(["--stdin-filename", "probe_mod.py", "-"], stdin=good) == []
