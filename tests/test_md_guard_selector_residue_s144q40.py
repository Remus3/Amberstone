"""RM-1146 (1), (3), (4): three static-read residues of the docs-guards
selector's `git ls-files` reading (`tools/md_guard_selector.py`
`index_walk_reasons`), found by the RM-1145 verifier.

- (1) An argv built by concatenating lists, `["git", "-C", "docs"] +
  ["ls-files", "guide.md"]`, was read from the root only: the `-C` in an
  earlier operand, and the call's `cwd=`, never reached the list holding
  `ls-files`.
- (3) A one-shot iterator passed as `tracked_md` was consumed by the first
  read of it (the suffix index, or the first pathspec checked), so every later
  read saw nothing.
- (4) A magic pathspec (`:(exclude)*.py`, `:!x`, `:^x`, `:(top)x`, `:/x`) was
  matched as a literal path. An exclude-only argv lists the rest of the index,
  `.md` included, and was not selected; a `:(top)` spec under `-C` names a
  path from the repo root.

Every fix is monotone (the old readings still select first). The magic cases
and the concatenation cases are also run through real git in a scratch repo:
the selector's verdict must equal "git listed a `.md`" for each one, so the
expected values are git's, not this file's. `:(icase)` and `:(attr:...)` are
read wide (not modelled) and are left out of that oracle on purpose.
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

_TRACKED_MD = ["README.md", "docs/guide.md", "docs/sub/deep.md"]
_REASON = ["<index walk: git ls-files>"]


def _body(call: str) -> str:
    return f"import subprocess\n\n\ndef test_walk():\n    subprocess.run({call})\n"


def _reasons(body: str, tracked_md=None, **kw) -> list:
    tracked = _TRACKED_MD if tracked_md is None else tracked_md
    return mgs.index_walk_reasons(ast.parse(body), tracked, **kw)


# (argv source, cwd keyword or None, selected) - each argv is a constant, so
# real git can run it too (the oracle below).
_MAGIC = {
    "exclude_only_long": ('["git", "ls-files", ":(exclude)*.py"]', None, True),
    "exclude_only_bang": ('["git", "ls-files", "--", ":!*.py"]', None, True),
    "exclude_only_caret": ('["git", "ls-files", ":^tools"]', None, True),
    "exclude_only_under_cwd": ('["git", "ls-files", ":!*.py"]', '"docs"', True),
    "top_long_under_C": ('["git", "-C", "tools", "ls-files", ":(top)docs/guide.md"]', None, True),
    "top_short_dir": ('["git", "-C", "tools", "ls-files", ":/docs"]', None, True),
    "top_short_colon": ('["git", "ls-files", ":/:docs/sub"]', None, True),
    "literal": ('["git", "ls-files", ":(literal)docs/guide.md"]', None, True),
    "glob_magic_under_C": ('["git", "-C", "docs", "ls-files", ":(glob)sub/*.md"]', None, True),
    "positive_with_an_exclude": ('["git", "ls-files", "docs", ":!docs/guide.md"]', None, True),
    "magic_under_cwd": ('["git", "ls-files", ":(literal)guide.md"]', '"docs"', True),
    # Not selected: a positive non-doc spec stays the bound, an exclude adds
    # nothing, and `:(top)` reads from the root, not from `-C`.
    "positive_tools_with_an_exclude": ('["git", "ls-files", "tools", ":(exclude)tools/*.json"]', None, False),
    "top_non_doc": ('["git", "ls-files", ":(top)tools/x.py"]', None, False),
    "top_ignores_C": ('["git", "-C", "docs", "ls-files", ":(top)tools/x.py"]', None, False),
    "top_is_not_read_under_C": ('["git", "-C", "docs", "ls-files", ":(top)guide.md"]', None, False),
    "glob_magic_py": ('["git", "ls-files", ":(glob)tools/*.py"]', None, False),
    "literal_under_C_misses": ('["git", "-C", "tools", "ls-files", ":(literal)guide.md"]', None, False),
    # An exclude-only argv lists the directory git runs in, not the index.
    "exclude_only_under_C": ('["git", "-C", "tools", "ls-files", ":!*.json"]', None, False),
}

_CONCAT = {
    "C_in_first_operand": ('["git", "-C", "docs"] + ["ls-files", "guide.md"]', None, True),
    "C_in_middle_operand": ('["git"] + ["-C", "docs"] + ["ls-files", "sub"]', None, True),
    "tuple_operands": ('("git", "-C", "docs") + ("ls-files", "guide.md")', None, True),
    "cwd_reaches_the_ls_files_operand": ('["git"] + ["ls-files", "guide.md"]', '"docs"', True),
    # The inner `+` of a three-operand chain is not read again with no `cwd=`.
    "cwd_reaches_an_inner_chain": (
        '["git", "ls-files", "guide.md"] + ["--full-name"] + ["--error-unmatch"]', '"docs"', True),
    "right_nested_chain": ('["git"] + (["-C", "docs"] + ["ls-files", "guide.md"])', None, True),
    "C_joins_and_misses": ('["git", "-C", "tools"] + ["ls-files", "guide.md"]', None, False),
    "C_and_py_glob": ('["git", "-C", "docs"] + ["ls-files", "--", "*.py"]', None, False),
}


def _call(argv: str, cwd) -> str:
    return argv if cwd is None else f"{argv}, cwd={cwd}"


@pytest.mark.parametrize("name", sorted(_MAGIC))
def test_a_magic_pathspec_is_read_by_its_magic(name):
    argv, cwd, selected = _MAGIC[name]
    assert _reasons(_body(_call(argv, cwd))) == (_REASON if selected else []), name


@pytest.mark.parametrize("spec", [":(icase)DOCS/GUIDE.MD", ":(attr:text)x.py", ":(nosuch)x.py"])
def test_an_unmodelled_magic_takes_the_wide_reading(spec):
    assert _reasons(_body(f'["git", "ls-files", "{spec}"]')) == _REASON


def test_an_exclude_only_argv_under_an_unreadable_C_is_wide():
    # The directory git lists cannot be read, so it may hold a doc.
    body = ('import subprocess\nfrom pathlib import Path\nROOT = Path(__file__).parent\n\n\n'
            'def test_walk():\n    subprocess.run(["git", "-C", str(ROOT), "ls-files", ":!*.py"])\n')
    assert _reasons(body) == _REASON


def test_a_magic_pathspec_in_a_helper_call_is_read_too():
    body = 'def _git(*a):\n    return a\n\n\ndef test_walk():\n    _git("ls-files", ":(exclude)*.py")\n'
    assert _reasons(body) == _REASON


@pytest.mark.parametrize("name", sorted(_CONCAT))
def test_a_concatenated_argv_is_read_as_one(name):
    argv, cwd, selected = _CONCAT[name]
    assert _reasons(_body(_call(argv, cwd))) == (_REASON if selected else []), name


@pytest.mark.parametrize("argv", [
    'GIT_C + ["ls-files", "guide.md"]',
    'pre() + ["ls-files", "guide.md"]',
])
def test_a_named_or_unreadable_operand_ahead_of_ls_files(argv):
    # GIT_C is a module constant holding `-C docs` (joined); `pre()` cannot be
    # read and may hold a `-C <dir>` (wide, like a starred prefix).
    body = ('import subprocess\nGIT_C = ["git", "-C", "docs"]\npre = list\n\n\n'
            f'def test_walk():\n    subprocess.run({argv})\n')
    assert _reasons(body) == _REASON


def test_the_root_reading_still_selects_a_concatenated_argv():
    # Monotone: a spec the root reading matches selects whatever `-C` says.
    assert _reasons(_body('["git", "-C", "tools"] + ["ls-files", "docs/guide.md"]')) == _REASON


def test_the_list_own_reading_still_selects_inside_a_chain():
    # Monotone over RM-1145: the list holding `ls-files` is still read on
    # its own (`-C docs` + guide.md), even though git itself would run in
    # docs/docs here.
    body = _body('["git", "-C", "docs"] + ["-C", "docs", "ls-files", "guide.md"]')
    assert _reasons(body) == _REASON


@pytest.mark.parametrize("call", [
    '["git"] + ["-C", "docs", "ls-files", "guide.md"], cwd="tools"',
    'args=["git"] + ["-C", "docs", "ls-files", "guide.md"], cwd="tools"',
])
def test_the_list_own_reading_ignores_the_chain_cwd(call):
    # Monotone over RM-1145 (found by the RM-1146 verifier, round 2): the
    # own reading starts where RM-1145 started it, not at the chain's cwd=.
    assert _reasons(_body(call)) == _REASON


def test_a_long_plus_chain_does_not_hit_the_recursion_limit():
    # Found by the RM-1146 verifier: a recursive flattening raised
    # RecursionError at about 1000 operands and crashed the whole selector.
    body = "X = " + " + ".join(['"a"'] * 3000) + "\n"
    assert _reasons(body) == []


@pytest.mark.parametrize("make", [iter, lambda xs: (x for x in xs)], ids=["iter", "generator"])
def test_a_one_shot_tracked_md_is_read_more_than_once(make):
    # The suffix index used to consume it, so every pathspec then saw nothing.
    body = _body('["git", "-C", "docs", "ls-files", "guide.md"]')
    assert _reasons(body, make(_TRACKED_MD)) == _REASON


def test_a_one_shot_tracked_md_with_md_suffixes_survives_a_first_miss():
    # md_suffixes given: the first argv's miss used to exhaust tracked_md, so
    # the second, a real doc walk, was dropped.
    body = ('import subprocess\n\n\ndef test_walk():\n'
            '    subprocess.run(["git", "ls-files", "x.json"])\n'
            '    subprocess.run(["git", "ls-files", "docs/guide.md"])\n')
    got = _reasons(body, iter(_TRACKED_MD), md_suffixes=mgs._md_suffix_index(_TRACKED_MD))
    assert got == _REASON


# ---- the git oracle -------------------------------------------------------

def _git_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture(scope="module")
def scratch_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("s144q40") / "repo"
    files = {
        "README.md": b"# r\n", "docs/guide.md": b"# g\n", "docs/sub/deep.md": b"# d\n",
        "tools/x.py": b"x = 1\n", "tools/a.json": b"{}\n",
    }
    for rel, data in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    for argv in (["init", "-q", "."], ["add", "--", "."]):
        subprocess.run([_GIT, *argv], cwd=str(repo), env=_git_env(), check=True,
                       capture_output=True, timeout=60)
    listed = subprocess.run([_GIT, "ls-files"], cwd=str(repo), env=_git_env(), check=True,
                            capture_output=True, text=True, timeout=60).stdout.split()
    assert sorted(p for p in listed if p.endswith(".md")) == sorted(_TRACKED_MD)
    return repo


def _argv_words(node) -> list:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _argv_words(node.left) + _argv_words(node.right)
    return list(ast.literal_eval(node))


def _git_lists_md(repo: Path, argv: str, cwd) -> bool:
    words = _argv_words(ast.parse(argv, mode="eval").body)
    run_in = repo if cwd is None else repo / ast.literal_eval(cwd)
    out = subprocess.run([_GIT, *words[1:]], cwd=str(run_in), env=_git_env(),
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, (argv, out.stderr)
    return any(line.endswith(".md") for line in out.stdout.splitlines())


@needs_git
@pytest.mark.parametrize("name", sorted(_MAGIC) + sorted(_CONCAT))
def test_each_expected_verdict_is_what_git_does(scratch_repo, name):
    argv, cwd, selected = {**_MAGIC, **_CONCAT}[name]
    assert _git_lists_md(scratch_repo, argv, cwd) is selected, name
