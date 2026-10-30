"""RM-1107: the docs-guards selector selects every test module whose git-index
enumeration can include a `.md` file.

`tools/md_guard_selector.py` selected a test module only when it NAMED a
tracked `.md` (a literal path or a `*.md` glob). A guard that walks the whole
git index names no `.md` at all - `git ls-files -z` with no pathspec,
`tests._repo_walk.tracked_relpaths(...)`, or `iter_repo_files` with a glob that
matches a `.md` basename - so a docs-only push that broke it ran nothing that
could see it (`.github/workflows/docs-guards.yml` runs exactly what the
selector prints; `ci.yml` path-ignores `**/*.md`). Measured on the s144 lane
tree: 68 of the 87 index-walking test modules were outside the selection, and
three of them read every tracked file's bytes, `.md` included
(`tests/test_text_line_endings.py` CRLF, `tests/test_requirements_lock_utf8_rm273.py`
UTF-16, `tests/test_third_party_notices_pkg.py` notice census).

The rule is about the ENUMERATION, not the filter after it: RM-273's guard
carries only a `.xml` literal (an exemption), yet reads the head of every
tracked `.md`. A filter-reading heuristic would have dropped it, and a false
negative is the direction this selector exists to prevent.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import md_guard_selector as mgs

REPO_ROOT = Path(__file__).resolve().parent.parent

_GIT = shutil.which("git")
needs_git = pytest.mark.skipif(_GIT is None, reason="git is not on PATH")

# A guard that walks the whole index and fails on any non-ASCII tracked byte.
# It names no `.md` anywhere, which is the whole point.
_ASCII_WALKER = '''\
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_tracked_file_is_ascii():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    bad = [rel for rel in out.split("\\0") if rel
           and any(b > 0x7F for b in (ROOT / rel).read_bytes())]
    assert bad == [], bad
'''


def _repo(tmp_path: Path, modules: dict) -> Path:
    """A throwaway git repo: one tracked doc with a non-ASCII byte plus the given
    test modules, all staged (the selector reads the index, not HEAD)."""
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs" / "new_note.md").write_bytes(b"# note\n\ncaf\xc3\xa9\n")
    for name, body in modules.items():
        (repo / "tests" / name).write_bytes(body.encode("ascii"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for argv in (["init", "-q", "."], ["add", "--", "."]):
        subprocess.run([_GIT, *argv], cwd=str(repo), env=env, check=True,
                       capture_output=True, timeout=60)
    return repo


def _selected(repo: Path) -> list:
    return mgs.select_md_guard_modules(repo)


@needs_git
def test_new_non_ascii_md_reddens_a_walker_the_selector_now_selects(tmp_path):
    repo = _repo(tmp_path, {"test_ascii_walk.py": _ASCII_WALKER})

    # Premise: the walker really goes red on the new .md alone.
    spec = importlib.util.spec_from_file_location(
        "s144q38_ascii_walk", repo / "tests" / "test_ascii_walk.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(AssertionError, match="new_note.md"):
        module.test_every_tracked_file_is_ascii()

    # The defect: a docs-only push ran nothing that could see that red.
    assert "tests/test_ascii_walk.py" in _selected(repo)


def _walker(call: str, imports: str = "import subprocess\n") -> str:
    return f"{imports}\n\ndef test_walk():\n    {call}\n"


_SELECTED = {
    "list_no_pathspec": _walker('subprocess.run(["git", "ls-files"], check=True)'),
    "list_flags_only": _walker(
        'subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--cached"])',
        "import subprocess\nROOT = '.'\n"),
    "helper_no_pathspec": _walker('_git("ls-files")', "def _git(*a):\n    return a\n"),
    "dir_pathspec_holding_md": _walker(
        'subprocess.run(["git", "ls-files", "--", "docs/"])'),
    "glob_pathspec_matching_md": _walker(
        'subprocess.run(["git", "ls-files", "--", "*.md"])'),
    "tracked_relpaths": _walker(
        "_repo_walk.tracked_relpaths()", "from tests import _repo_walk\n"),
    "tracked_relpaths_bare": _walker(
        "tracked_relpaths(str(ROOT))",
        "from tests._repo_walk import tracked_relpaths\nROOT = '.'\n"),
    "iter_star_glob": _walker(
        '_repo_walk.iter_repo_files(patterns=("*",))', "from tests import _repo_walk\n"),
    "repo_files_dot_star": _walker(
        '_repo_walk.repo_files(".", ["*.*"])', "from tests import _repo_walk\n"),
    "iter_patterns_constant": _walker(
        "_repo_walk.iter_repo_files(patterns=PATTERNS)",
        "from tests import _repo_walk\nPATTERNS = ('*.py', '*.md')\n"),
    "pathspec_constant_holding_md": _walker(
        'subprocess.run(["git", "ls-files", "--", DOCS])', "import subprocess\nDOCS = 'docs'\n"),
    # Wide on purpose: an argument that cannot be read statically, an argv
    # bound to a name, or one handed to any callable still selects - the
    # false-positive direction costs CI seconds, the other one is the defect.
    "iter_patterns_unreadable": _walker(
        "_repo_walk.iter_repo_files('.', make())",
        "from tests import _repo_walk\nmake = tuple\n"),
    "pathspec_unreadable": _walker(
        'subprocess.run(["git", "ls-files", "--", pick()])', "import subprocess\npick = str\n"),
    "argv_bound_to_a_name": _walker(
        "subprocess.run(ARGV)", 'import subprocess\nARGV = ["git", "ls-files", "-z"]\n'),
    "argv_handed_to_a_helper": _walker('harden(["git", "ls-files", "--others"])',
                                       "def harden(argv):\n    return argv\n"),
}

_NOT_SELECTED = {
    "py_pathspec": _walker('subprocess.run(["git", "ls-files", "--", "*.py"])'),
    "dir_pathspec_without_md": _walker(
        'subprocess.run(["git", "ls-files", "-z", "--", "tests/"])'),
    "constant_pathspec": _walker(
        'subprocess.run(["git", "ls-files", "--", REL])', "import subprocess\nREL = 'x.json'\n"),
    "starred_pathspec": _walker(
        'subprocess.run(["git", "ls-files", "-z", *PATTERNS])',
        "import subprocess\nPATTERNS = ('*.py',)\n"),
    "helper_with_pathspec": _walker(
        '_git("ls-files", "--error-unmatch", "ops/x.json")',
        "def _git(*a):\n    return a\n"),
    "iter_default_py": _walker(
        "_repo_walk.iter_repo_files()", "from tests import _repo_walk\n"),
    "iter_py_glob": _walker(
        '_repo_walk.repo_files(".", ("*.py", "*.js"))', "from tests import _repo_walk\n"),
    "verb_set": _walker('assert "x" in {"merge-base", "ls-files"}', ""),
    "prose_mention": _walker('x = "runs git ls-files over the tree"', ""),
}


@needs_git
def test_every_whole_index_enumeration_shape_selects(tmp_path):
    modules = {f"test_{k}.py": v for k, v in _SELECTED.items()}
    modules.update({f"test_not_{k}.py": v for k, v in _NOT_SELECTED.items()})
    got = set(_selected(_repo(tmp_path, modules)))
    missed = sorted(k for k in _SELECTED if f"tests/test_{k}.py" not in got)
    assert missed == [], f"whole-index walkers left out of the docs-guards run: {missed}"
    over = sorted(k for k in _NOT_SELECTED if f"tests/test_not_{k}.py" in got)
    assert over == [], f"scoped / non-walking modules selected: {over}"


_HISTORY_WALKERS = {
    # s144 L5 merger: a whole-index walker that ALSO asks git for history
    # cannot run in docs-guards.yml, which checks out at fetch-depth: 1
    # (tests/test_ci_checkout_history_depth.py). The RM-1107 widening selected
    # four such modules; the full suite (fetch-depth: 0) still runs them.
    "cat_file": _walker('subprocess.run(["git", "ls-files"]); '
                        'subprocess.run(["git", "cat-file", "-e", "abc^:x.md"])'),
    "diff_filter": _walker('subprocess.run(["git", "ls-files"]); '
                           'subprocess.run(["git", "log", "--all", "--diff-filter=DR"])'),
    "rev_list": _walker('subprocess.run(["git", "ls-files"]); '
                        'subprocess.run(["git", "rev-list", "HEAD"])'),
}


@needs_git
def test_a_history_reading_walker_is_not_selected(tmp_path):
    modules = {f"test_hist_{k}.py": v for k, v in _HISTORY_WALKERS.items()}
    modules["test_plain_walk.py"] = _SELECTED["list_no_pathspec"]
    got = set(_selected(_repo(tmp_path, modules)))
    assert "tests/test_plain_walk.py" in got, "control: the plain walker must still select"
    over = sorted(k for k in _HISTORY_WALKERS if f"tests/test_hist_{k}.py" in got)
    assert over == [], f"history-reading walkers selected into the depth-1 docs-guards run: {over}"


@needs_git
def test_explain_names_the_walk(tmp_path):
    repo = _repo(tmp_path, {"test_ascii_walk.py": _ASCII_WALKER})
    detail = mgs.select_md_guard_modules(repo, explain=True)
    assert any("ls-files" in reason for reason in detail["tests/test_ascii_walk.py"])


_LIVE_WALKERS = (
    "tests/test_text_line_endings.py",           # CRLF over every tracked file
    "tests/test_requirements_lock_utf8_rm273.py",  # UTF-16 head of every tracked file
    "tests/test_third_party_notices_pkg.py",     # census of the whole index
)
_LIVE_SCOPED = (
    "tests/test_data_meta_ascii.py",             # git ls-files -- data/meta/*.json
    "tests/test_githooks_eol_lf.py",             # git ls-files -- .githooks/
    "tests/test_rm413_wal_pragma_result_checked.py",  # iter_repo_files() = *.py
    "tests/test_requirements_hashed_lock_pubrepo_e.py",  # ls-files -- requirements.lock
)


@needs_git
def test_live_selection_holds_the_whole_index_md_readers_and_not_the_scoped():
    got = set(mgs.select_md_guard_modules(REPO_ROOT))
    assert [m for m in _LIVE_WALKERS if m not in got] == []
    assert [m for m in _LIVE_SCOPED if m in got] == []
    # The walk helper itself is not a test module: its callers are selected.
    assert "tests/_repo_walk.py" not in got
