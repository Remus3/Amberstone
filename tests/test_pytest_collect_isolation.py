"""Pin: a repo-root pytest run never imports untrusted or generated trees.

Incident (2026-10-09 18:27 local): a merge agent ran
``fleet_suite_gate.py run ... -- python -m pytest -q $(cat <list file>)`` whose
list file did not exist yet, so the ``$(...)`` expanded to NOTHING and the gate
ran a BARE ``pytest -q`` from the repo root. ``pytest.ini`` had no
``testpaths`` and its ``norecursedirs`` did not name the channel dir, so pytest
walked the whole checkout: 930 collection errors in 16 s, and on the way it
IMPORTED the sibling test modules delivered verbatim under the gitignored
``moon_sync_inbox/`` (from-CS-verbatim, from-RSC-verbatim) - 25 ``.pyc`` files
written there, i.e. another project's code executed in RC's environment. The
same walk also reached ``ops/runtime/responder_export/<sha>/`` (a full copy of
the repo) and every other generated tree.

Two defences, pinned separately because they fail separately:

1. ``testpaths = tests agents/daemon_slayer`` - a bare root run (no path, or
   only ``-k`` / ``-m``) collects the two RC suite roots and nothing else.
2. ``norecursedirs`` names every untrusted or generated tree, so an explicit
   ``pytest .`` (which bypasses ``testpaths``) still never descends into them.

Both are proven BEHAVIOURALLY on a throwaway tree under ``tmp_path`` that
carries a byte copy of RC's real ``pytest.ini`` and planted modules that leave
a sentinel file if they are ever imported. The live inbox is never touched.

The third test is the converse guard: a generic name such as ``data`` or
``logs`` in ``norecursedirs`` would silently drop a real RC test directory of
that name, so every test-bearing directory under the two suite roots is
checked against the exact matcher pytest uses.
"""

from __future__ import annotations

import configparser
import os
import subprocess
import sys
from pathlib import Path

from _pytest.pathlib import fnmatch_ex

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTEST_INI = REPO_ROOT / "pytest.ini"

SUITE_ROOTS = ("tests", "agents/daemon_slayer")

# Trees a root-level run must never import. Each one is planted below.
UNTRUSTED_OR_GENERATED = (
    "moon_sync_inbox",
    ".claude",
    "worktrees",
    "rc-worktrees",
    "ops/runtime",
    "responder_export",
    "_scratch",
    "_archive",
    "Share",
    "data",
    "logs",
    "atlas/snapshots",
)

SENTINEL = "IMPORTED.flag"

# Leaves a sentinel next to itself, then fails loudly, if it is ever imported.
_PLANTED_SOURCE = '''from pathlib import Path

Path(__file__).with_name("IMPORTED.flag").write_text("imported", encoding="ascii")
raise RuntimeError("planted module was imported: " + __file__)
'''

_OK_TEST = "def test_ok():\n    pass\n"

# Planted relative paths: every untrusted / generated tree a bare or explicit
# root run used to reach, each with a test module and (where a sibling payload
# could carry one) a conftest.py, which pytest also imports on directory entry.
_PLANTED = (
    "moon_sync_inbox/from-CS-verbatim/tests/test_planted.py",
    "moon_sync_inbox/from-CS-verbatim/conftest.py",
    "moon_sync_inbox/from-RSC-verbatim/tests/test_planted.py",
    "moon_sync_inbox/2026-10-09-0930-from-MAIN-FLEET-KIT-v14/test_planted.py",
    "ops/runtime/responder_export/abc123/tests/test_planted.py",
    "ops/runtime/responder_export/abc123/conftest.py",
    ".claude/worktrees/agent-x/tests/test_planted.py",
    "rc-worktrees/lane-1/tests/test_planted.py",
    "_scratch/test_planted.py",
    "docs/_archive/test_planted.py",
    "Share/src/agents/daemon_slayer/tests/test_planted.py",
    "data/test_planted.py",
    "logs/test_planted.py",
    "atlas/snapshots/test_planted.py",
)

_REAL = (
    "tests/test_ok.py",
    "agents/daemon_slayer/tests/test_ds_ok.py",
)


def _ini() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read(PYTEST_INI, encoding="ascii")
    assert parser.has_section("pytest"), "pytest.ini lost its [pytest] section"
    return parser


def _norecursedirs() -> list[str]:
    return _ini().get("pytest", "norecursedirs", fallback="").split()


def _testpaths() -> list[str]:
    return _ini().get("pytest", "testpaths", fallback="").split()


def _build_tree(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    # Byte copy, so the probe runs RC's real collection config, not a restatement.
    (repo / "pytest.ini").write_bytes(PYTEST_INI.read_bytes())
    for rel in _REAL:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_OK_TEST.replace("test_ok", Path(rel).stem), encoding="ascii")
    # A benign module outside both suite roots: reachable by an explicit run,
    # never by a bare one (testpaths).
    side = repo / "tools" / "tests" / "test_side_ok.py"
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(_OK_TEST.replace("test_ok", "test_side_ok"), encoding="ascii")
    for rel in _PLANTED:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_PLANTED_SOURCE, encoding="ascii")
    return repo


def _collect(repo: Path, *args: str) -> tuple[int, str, list[str]]:
    env = dict(os.environ)
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTEST_CURRENT_TEST",
                "PYTHONDONTWRITEBYTECODE"):
        env.pop(key, None)
    popen_kwargs = {}
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-p", "no:cacheprovider", "-p", "no:randomly", *args],
        cwd=str(repo),
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        **popen_kwargs,
    )
    output = proc.stdout + proc.stderr
    nodeids = sorted(ln.strip() for ln in proc.stdout.splitlines() if "::" in ln)
    return proc.returncode, output, nodeids


def _assert_nothing_planted_ran(repo: Path, output: str) -> None:
    flags = sorted(p.relative_to(repo).as_posix() for p in repo.rglob(SENTINEL))
    assert not flags, f"planted modules were IMPORTED: {flags}\n{output}"
    caches = sorted(
        p.relative_to(repo).as_posix()
        for rel in _PLANTED
        for p in (repo / rel).parent.glob("__pycache__")
    )
    assert not caches, f"bytecode written beside planted modules: {caches}\n{output}"


def test_ini_pins_testpaths_and_untrusted_norecursedirs():
    assert _testpaths() == list(SUITE_ROOTS)
    patterns = _norecursedirs()
    missing = [name for name in UNTRUSTED_OR_GENERATED if name not in patterns]
    assert not missing, f"pytest.ini norecursedirs lost: {missing}"


def test_bare_root_run_collects_only_the_suite_roots(tmp_path):
    """The incident's exact shape: ``pytest`` with no path from the root."""
    repo = _build_tree(tmp_path)
    rc, output, nodeids = _collect(repo)
    assert rc == 0, output
    assert nodeids == [
        "agents/daemon_slayer/tests/test_ds_ok.py::test_ds_ok",
        "tests/test_ok.py::test_ok",
    ], output
    _assert_nothing_planted_ran(repo, output)


def test_explicit_root_run_never_descends_into_untrusted_trees(tmp_path):
    """``pytest .`` bypasses testpaths, so norecursedirs alone must hold."""
    repo = _build_tree(tmp_path)
    rc, output, nodeids = _collect(repo, ".")
    assert rc == 0, output
    assert nodeids == [
        "agents/daemon_slayer/tests/test_ds_ok.py::test_ds_ok",
        "tests/test_ok.py::test_ok",
        "tools/tests/test_side_ok.py::test_side_ok",
    ], output
    _assert_nothing_planted_ran(repo, output)


def test_no_real_test_directory_is_excluded():
    """A generic norecursedirs name must never swallow an RC test directory.

    Every directory between a suite root and a test module or conftest.py is
    run through pytest's own matcher. A hit means a real test would silently
    stop being collected - rename the directory or narrow the pattern.
    """
    patterns = _norecursedirs()
    checked = 0
    offenders: list[str] = []
    for root in SUITE_ROOTS:
        base = REPO_ROOT / root
        assert base.is_dir(), f"suite root missing: {root}"
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            holds_tests = any(
                f == "conftest.py"
                or (f.endswith(".py") and (f.startswith("test_") or f.endswith("_test.py")))
                for f in filenames
            )
            if not holds_tests:
                continue
            here = Path(dirpath)
            chain = [here, *here.parents]
            for anc in chain:
                if anc == REPO_ROOT or REPO_ROOT not in anc.parents:
                    break
                checked += 1
                hits = [pat for pat in patterns if fnmatch_ex(pat, anc)]
                if hits:
                    rel = anc.relative_to(REPO_ROOT).as_posix()
                    offenders.append(f"{rel} matched by {hits}")
    assert checked >= 10, f"walk is vacuous: only {checked} directories checked"
    assert not offenders, "\n".join(sorted(set(offenders)))
