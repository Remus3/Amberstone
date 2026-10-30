"""RM-1145 (a): the docs-guards selector reads an `ls-files` pathspec in the
directory git resolves it in.

`tools/md_guard_selector.py` (RM-1107) matched every `git ls-files` pathspec
against repo-relative `.md` paths. git resolves a pathspec in the directory the
command runs in - the argv's `-C <dir>` flags, or the call's `cwd=` - so
`git -C docs ls-files -- guide.md` reads `docs/guide.md`, and the root reading
(`guide.md`) missed it. A test that walks a subdirectory holding a tracked
`.md` that way was left out of the docs-guards run.

The fix is monotone: the root reading still selects. A constant `-C` (a string
literal or a module constant) is joined; a `-C` or `cwd=` that cannot be read
statically (every live one is `str(<path>)`), or a helper call whose own
directory is not visible, matches the spec against every segment-boundary
suffix of a tracked `.md` - "some directory could make it reach a doc". So a
`requirements.lock` or `*.py` spec still selects nothing, wherever it runs.
"""
from __future__ import annotations

import ast
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tools import md_guard_selector as mgs

_GIT = shutil.which("git")
needs_git = pytest.mark.skipif(_GIT is None, reason="git is not on PATH")

_TRACKED_MD = ["docs/guide.md", "docs/sub/deep.md", "README.md"]


def _reasons(body: str) -> list:
    return mgs.index_walk_reasons(ast.parse(body), _TRACKED_MD)


def _walker(call: str, imports: str = "import subprocess\n") -> str:
    return f"{imports}\n\ndef test_walk():\n    {call}\n"


_ROOTED = "import subprocess\nfrom pathlib import Path\nROOT = Path(__file__).resolve().parent.parent\n"

_SELECTED = {
    "constant_C": _walker('subprocess.run(["git", "-C", "docs", "ls-files", "-z", "--", "guide.md"])'),
    "module_constant_C": _walker('subprocess.run(["git", "-C", SUB, "ls-files", "guide.md"])',
                                 "import subprocess\nSUB = 'docs'\n"),
    "constant_C_dir_spec": _walker('subprocess.run(["git", "-C", "docs", "ls-files", "sub"])'),
    "two_C_flags": _walker(
        'subprocess.run(["git", "-C", "tests", "-C", "../docs", "ls-files", "guide.md"])'),
    "unreadable_C": _walker('subprocess.run(["git", "-C", str(ROOT / "docs"), "ls-files", "guide.md"])',
                            _ROOTED),
    # The live shape (tests/test_data_retention_rm117_tracked_patches.py):
    # a local name built in the test, then `-C str(name)` and a subdir spec.
    "unreadable_C_subdir_spec": _walker(
        'data = ROOT / "docs"; subprocess.run(["git", "-C", str(data), "ls-files", "sub"])', _ROOTED),
    "unreadable_cwd": _walker('subprocess.run(["git", "ls-files", "guide.md"], cwd=ROOT / "docs")',
                              _ROOTED),
    "constant_cwd": _walker('subprocess.run(["git", "ls-files", "guide.md"], cwd="docs")'),
    "kwargs_call": _walker('subprocess.run(["git", "ls-files", "guide.md"], **OPTS)',
                           "import subprocess\nOPTS = {}\n"),
    "helper_call": _walker('_git("ls-files", "guide.md")', "def _git(*a):\n    return a\n"),
    "helper_call_with_C": _walker('_git("-C", "docs", "ls-files", "guide.md")',
                                  "def _git(*a):\n    return a\n"),
    "helper_call_with_unreadable_C": _walker('_git("-C", str(ROOT / "docs"), "ls-files", "guide.md")',
                                             _ROOTED + "\n\ndef _git(*a):\n    return a\n"),
    # A starred prefix that cannot be read may hold a `-C <dir>`.
    "starred_prefix": _walker('subprocess.run(["git", *pre(), "ls-files", "guide.md"])',
                              "import subprocess\npre = list\n"),
    "args_keyword_cwd": _walker('subprocess.run(args=["git", "ls-files", "guide.md"], cwd=ROOT / "docs")',
                                _ROOTED),
}

_NOT_SELECTED = {
    # The constant join is used, not the wide reading: tests/guide.md is no doc.
    "constant_C_misses": _walker('subprocess.run(["git", "-C", "tests", "ls-files", "guide.md"])'),
    "constant_C_py_glob": _walker('subprocess.run(["git", "-C", "docs", "ls-files", "--", "*.py"])'),
    "unreadable_C_lock": _walker(
        'subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", "requirements.lock"])', _ROOTED),
    "unreadable_cwd_json": _walker('subprocess.run(["git", "ls-files", "x.json"], cwd=ROOT)', _ROOTED),
    "helper_json": _walker('_git("ls-files", "--error-unmatch", "ops/x.json")',
                           "def _git(*a):\n    return a\n"),
    "helper_call_with_C_py_glob": _walker('_git("-C", "docs", "ls-files", "*.py")',
                                          "def _git(*a):\n    return a\n"),
    # "ls-files" after a non-literal argument is data, not a git argv.
    "verb_after_a_variable": _walker('check(out, "ls-files", "guide.md")',
                                     "out = ''\n\ndef check(*a):\n    return a\n"),
    "root_reading_misses": _walker('subprocess.run(["git", "ls-files", "guide.md"])'),
}


@pytest.mark.parametrize("name", sorted(_SELECTED))
def test_a_pathspec_reaching_a_doc_from_its_directory_selects(name):
    assert _reasons(_SELECTED[name]) == ["<index walk: git ls-files>"], name


@pytest.mark.parametrize("name", sorted(_NOT_SELECTED))
def test_a_pathspec_that_cannot_reach_a_doc_does_not_select(name):
    assert _reasons(_NOT_SELECTED[name]) == [], name


def test_a_constant_C_that_leaves_the_repo_takes_the_wide_reading():
    # `-C ..` then `guide.md` names a file outside the index root; read wide,
    # the spec matches the suffix of docs/guide.md and selects.
    body = _walker('subprocess.run(["git", "-C", "..", "ls-files", "guide.md"])')
    assert _reasons(body) == ["<index walk: git ls-files>"]


def test_the_root_reading_still_selects_under_a_constant_C():
    # Monotone over RM-1107: a spec the root reading matches selects even when
    # the `-C` join would miss it.
    body = _walker('subprocess.run(["git", "-C", "tests", "ls-files", "docs/guide.md"])')
    assert _reasons(body) == ["<index walk: git ls-files>"]


@pytest.mark.parametrize("call, reason", [
    ('repo_files(".", "*.md", "ls-files", "x.py")', "<index walk: repo_files>"),
    ('tracked_relpaths("x", "ls-files", "x.py")', "<index walk: tracked_relpaths>"),
    # The helper-verb check selects here too; the glob walker still reports.
    ('repo_files(".", "*.md", "ls-files", "guide.md")', "<index walk: repo_files>"),
])
def test_a_later_ls_files_literal_never_shadows_the_other_walkers(call, reason):
    # Monotone: the helper-verb check runs on its own, so a lister or glob
    # walker the base selected stays selected.
    assert reason in _reasons(_walker(call, ""))


def _repo(tmp_path: Path, modules: dict) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs" / "sub").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "docs" / "guide.md").write_bytes(b"# guide\n")
    (repo / "docs" / "sub" / "deep.md").write_bytes(b"# deep\n")
    for name, body in modules.items():
        (repo / "tests" / name).write_bytes(body.encode("ascii"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    for argv in (["init", "-q", "."], ["add", "--", "."]):
        subprocess.run([_GIT, *argv], cwd=str(repo), env=env, check=True,
                       capture_output=True, timeout=60)
    return repo


@needs_git
def test_the_selector_end_to_end_picks_the_subdir_walker(tmp_path):
    repo = _repo(tmp_path, {"test_sub_walk.py": _SELECTED["unreadable_C_subdir_spec"],
                            "test_lock_walk.py": _NOT_SELECTED["unreadable_C_lock"]})
    got = mgs.select_md_guard_modules(repo)
    assert "tests/test_sub_walk.py" in got
    assert "tests/test_lock_walk.py" not in got
