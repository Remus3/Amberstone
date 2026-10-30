"""RM-722 (b) dead-artifact drift guard: no test package that is only a shell.

`tests/audit7_h01/` and `tests/phase6_bridge_cli/` each tracked one 0-byte
`__init__.py` (blob e69de29) and nothing else. Both test modules,
`tests/phase6_bridge_cli/test_bridge_cli.py` and
`tests/audit7_h01/test_h01_bridge_health_alarm.py`, were deleted with the
ADR-012 bridge decommission (b44fdb5c8), which left the two shells behind, and
the only non-doc mentions at removal were the historical audit snapshots
`ops/audit/p2w5_slices.json` / `p2w5_truth_gate_report.json`, which record a
past tree and read nothing. No conftest, pytest.ini, CI step or import names
either package. An empty package collects nothing, so it is pure clutter
that reads as a missing test suite to an outsider.

The general rule pins the class, not just the two names: under either test
root, no tracked directory may hold an `__init__.py` as its ONLY tracked file.
The check reads the git index (ADR-015, `tests/_repo_walk.tracked_relpaths`),
never the disk, so an untracked `__pycache__/` left behind in a checkout does
not fail it. If you add a test package, add its tests in the same commit.
"""
from __future__ import annotations

from collections import defaultdict

import pytest

from tests._repo_walk import tracked_relpaths

_TEST_ROOTS = ("tests/", "agents/daemon_slayer/tests/")
_REMOVED = ("tests/audit7_h01/", "tests/phase6_bridge_cli/")


@pytest.fixture(scope="module")
def tracked() -> frozenset[str]:
    paths = tracked_relpaths()
    # None means git was unavailable; an absence check over nothing passes
    # vacuously, so refuse rather than skip.
    assert paths is not None, "git index unavailable - the guard cannot run"
    # Anchor: the index must reach both test roots.
    assert "tests/_repo_walk.py" in paths
    assert "agents/daemon_slayer/tests/__init__.py" in paths
    return paths


def _files_by_dir(paths: frozenset[str]) -> dict[str, set[str]]:
    by_dir: dict[str, set[str]] = defaultdict(set)
    for rel in paths:
        if not rel.startswith(_TEST_ROOTS) or "/" not in rel:
            continue
        parent, name = rel.rsplit("/", 1)
        by_dir[parent + "/"].add(name)
    return by_dir


def _shells(by_dir: dict[str, set[str]]) -> list[str]:
    """Directories whose only tracked file is __init__.py and that hold no
    tracked subdirectory (a namespace parent of real tests is not a shell)."""
    return sorted(
        d for d, names in by_dir.items()
        if names == {"__init__.py"}
        and not any(o != d and o.startswith(d) for o in by_dir)
    )


def test_rm722_removed_packages_stay_removed(tracked: frozenset[str]) -> None:
    back = sorted(p for p in tracked if p.startswith(_REMOVED))
    assert not back, (
        f"{back} tracked again. RM-722 (b) removed these empty packages; "
        "add a test package together with its tests."
    )


def test_no_test_package_tracks_only_its_init(tracked: frozenset[str]) -> None:
    by_dir = _files_by_dir(tracked)
    # Anchor: an empty grouping would pass vacuously.
    assert "tests/" in by_dir and "agents/daemon_slayer/tests/" in by_dir
    shells = _shells(by_dir)
    assert not shells, (
        f"test package(s) tracking only __init__.py: {shells}. An empty "
        "package collects nothing; add its tests or remove it (RM-722 (b))."
    )


def test_shell_detector_flags_a_synthetic_shell() -> None:
    # Positive control: the detector must see the class it guards.
    synthetic = frozenset({
        "tests/__init__.py",
        "tests/test_a.py",
        "tests/shell_pkg/__init__.py",
        "tests/real_pkg/__init__.py",
        "tests/real_pkg/test_b.py",
        "tests/parent_pkg/__init__.py",
        "tests/parent_pkg/child/test_c.py",
    })
    by_dir = _files_by_dir(synthetic)
    shells = _shells(by_dir)
    assert shells == ["tests/shell_pkg/"]
