"""S144-P-597 - ruff PTH112 / B904 / FURB105 / FURB192 held at a named baseline in TEST code.

Measured 2026-11-09 with ``ruff check --isolated --preview`` (target py39) over ``tests/``: seven findings in six files.
Five test sites became the clean spelling: ``tests/test_inbox_responder_runner.py`` asks ``Path("/proc/self/fd").is_dir()``
for its skipif, ``tests/test_routes_state_stream_true_audit_s144.py`` chains the AssertionError to the ``_Runaway`` it
replaces (``from runaway``), ``tests/test_glob_to_path_glob_ratchet_s144p525.py`` takes ``min(...)`` for ``sorted(...)[0]``,
and ``tests/test_furb105_print_empty_string_ratchet_s144p133.py`` prints a NAME bound to the empty string so the
byte-identity premise it pins still compares ``print(x)`` with a bare ``print()``. The other findings stay baselined:

- ``tests/_replace_faults.py`` (one site): the control arm of the RM-411 fault harness reads the raw ``os`` layer on purpose,
  because ``Path.is_dir`` / ``Path.mkdir`` are the very layer the harness faults, so the control cannot ask them.

PERF102 is NOT in this set: ``tests/test_dict_iter_unused_half_ratchet_s144p139.py`` and ``tests/test_perf102_ratchet_s144p178.py``
carry the ``.items()`` shape on purpose as the premise they pin, and ``tests/test_rank_tier_live_budget.py`` is changed by
``lane/queue``.

The baseline only shrinks: ANY new finding, or a second finding in a baselined file, fails
``test_no_file_exceeds_its_baseline``. The run uses NO config (``--isolated``) so a per-file-ignore cannot hide a finding.
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

_RULES = "PTH112,B904,FURB105,FURB192"
# file -> findings. Only shrinks; each entry is an unconverted site, not an exemption.
_BASELINE: dict[str, int] = {
    "tests/_replace_faults.py": 1,  # the control arm reads the raw os layer the harness does not fault
}
_FIXED = (
    "tests/test_inbox_responder_runner.py",
    "tests/test_routes_state_stream_true_audit_s144.py",
    "tests/test_glob_to_path_glob_ratchet_s144p525.py",
    "tests/test_furb105_print_empty_string_ratchet_s144p133.py",
)


def _ruff(args: list[str], stdin: str | None = None) -> list[dict]:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--preview", "--target-version", "py39",
         "--no-fix", "--no-cache", "--output-format", "json", "--select", _RULES, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=300, input=stdin, check=False, **kwargs,
    )
    # ruff exits 1 when it reports anything; 2 is a real failure.
    assert proc.returncode in (0, 1), proc.stderr[-400:]
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def held_counts() -> dict[str, int]:
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    held = {t for t in tracked if t.startswith("tests/")}
    assert len(held) > 300, "the tracked-file walk returned almost nothing under tests/"
    counts: collections.Counter = collections.Counter()
    for d in _ruff(["tests"]):
        rel = relative_posix(Path(d["filename"]).resolve())
        if rel in held:
            counts[rel] += 1
    return dict(counts)


def test_no_file_exceeds_its_baseline(held_counts):
    over = {f: n for f, n in held_counts.items() if n > _BASELINE.get(f, 0)}
    assert not over, f"ruff {_RULES} findings above the baseline, file: count: {over}"


def test_the_baseline_only_shrinks(held_counts):
    stale = {f: n for f, n in _BASELINE.items() if held_counts.get(f, 0) < n}
    assert not stale, f"baseline entries to lower or remove (fixed since): {stale}"


def test_the_fixed_files_are_clean_and_tracked(held_counts):
    tracked = {relative_posix(p) for p in repo_files(REPO_ROOT, ("*.py",))}
    for rel in _FIXED:
        assert rel in tracked, rel
        assert rel not in _BASELINE, rel
        assert held_counts.get(rel, 0) == 0, rel


def test_the_fence_is_not_empty_of_findings_by_accident():
    """A positive control: each rule fires on the pattern the ratchet exists for."""
    probe = (
        "import os\n"
        "os.path.isdir('a')\n"
        "try:\n    pass\nexcept ValueError:\n    raise KeyError('x')\n"
        "print('')\n"
        "sorted([3, 1])[0]\n"
    )
    found = _ruff(["--stdin-filename", "probe.py", "-"], stdin=probe)
    assert sorted(d["code"] for d in found) == ["B904", "FURB105", "FURB192", "PTH112"]


def test_print_name_bound_to_empty_string_still_writes_the_bare_print_bytes():
    """The rewritten FURB105 test premise: ``print(empty)`` and ``print()`` write the same bytes."""
    import contextlib
    import io

    empty = ""
    old, new = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(old):
        print(empty)
    with contextlib.redirect_stdout(new):
        print()
    assert old.getvalue() == new.getvalue() == "\n"


def test_min_of_a_set_of_names_is_the_first_sorted_name():
    """The rewritten FURB192 site: ``min`` and ``sorted()[0]`` pick the same element."""
    names = {"Zed", "Yi", "Ahri", "Xin"}
    assert sorted(names) == ["Ahri", "Xin", "Yi", "Zed"]
    assert min(names) == "Ahri"
