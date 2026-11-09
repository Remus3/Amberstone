"""RM-1147: two more static-read residues of the docs-guards selector's
`git ls-files` reading (`tools/md_guard_selector.py` `index_walk_reasons`),
found by the RM-1146 round-3 verifier, plus one recorded decision.

- (a) An option's separate value was read as a pathspec. `git ls-files -x
  "*.py"` lists the whole index, `.md` included, but `*.py` was taken as the
  only spec, so the walker was not selected. Same for `-X <file>`,
  `--exclude <pattern>`, `--exclude-from <file>`, `--exclude-per-directory
  <file>`, `--with-tree <tree-ish>` and `--format <format>`, in a short
  cluster (`-tx <pattern>`) and as a long-option abbreviation (`--form`).
- (b) A call's `cwd=` did not reach an argv wrapped in another call,
  `subprocess.run(list(["git"] + ["ls-files", "guide.md"]), cwd="docs")`.
- (c) `list(tracked_md)` raises TypeError on a non-iterable such as None. KEPT
  on purpose: a None read as "no docs" would drop every walker silently, and
  a false negative is this selector's defect. Reverses if: a caller is found
  passing None (or another non-iterable) for a reason that is not a bug.

Every fix is monotone (the old readings still select first). The (a) and (b)
verdicts are also run through real git in a scratch repo: the selector's
verdict must equal "git listed a `.md`", so the expected values are git's.
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
# The empty tree: every repo resolves it, so `--with-tree` needs no commit.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _body(call: str) -> str:
    return f"import subprocess\n\n\ndef test_walk():\n    subprocess.run({call})\n"


def _reasons(body: str, tracked_md=None) -> list:
    tracked = _TRACKED_MD if tracked_md is None else tracked_md
    return mgs.index_walk_reasons(ast.parse(body), tracked)


# (argv source, cwd keyword or None, selected) - each argv is a constant (or a
# constant wrapped in list() / tuple()), so real git can run it too.
_OPTION_ARGS = {
    "x_short": ('["git", "ls-files", "-x", "*.py"]', None, True),
    "exclude_long": ('["git", "ls-files", "--exclude", "*.py"]', None, True),
    "X_short": ('["git", "ls-files", "-X", "tools/x.py"]', None, True),
    "exclude_from": ('["git", "ls-files", "--exclude-from", "tools/x.py"]', None, True),
    "exclude_per_directory": ('["git", "ls-files", "--exclude-per-directory", "tools/x.py"]',
                              None, True),
    "with_tree": (f'["git", "ls-files", "--with-tree", "{_EMPTY_TREE}"]', None, True),
    "format": ('["git", "ls-files", "--format", "%(path)"]', None, True),
    "format_abbreviated": ('["git", "ls-files", "--form", "%(path)"]', None, True),
    "exclude_from_abbreviated": ('["git", "ls-files", "--exclude-f", "tools/x.py"]', None, True),
    "short_cluster": ('["git", "ls-files", "-tx", "*.py"]', None, True),
    "option_value_under_C": ('["git", "-C", "docs", "ls-files", "-x", "*.py"]', None, True),
    "option_value_under_cwd": ('["git", "ls-files", "-x", "*.py"]', '"docs"', True),
    # Already selected before the fix (an attached value starts with "-").
    "attached_short": ('["git", "ls-files", "-x*.py"]', None, True),
    "attached_long": ('["git", "ls-files", "--exclude=*.py"]', None, True),
    # Not selected: the value is skipped, but a real pathspec still bounds it.
    "value_then_tools": ('["git", "ls-files", "-x", "*.json", "tools"]', None, False),
    "format_then_tools": ('["git", "ls-files", "--format", "%(path)", "tools"]', None, False),
    "attached_short_then_tools": ('["git", "ls-files", "-x*.json", "tools"]', None, False),
    "attached_long_then_tools": ('["git", "ls-files", "--exclude=*.json", "tools"]', None, False),
    # After `--` every word is a pathspec, an option-looking one included.
    "after_double_dash": ('["git", "ls-files", "--", "-x", "*.py"]', None, False),
    # A no-value option does not swallow the spec after it.
    "exclude_standard": ('["git", "ls-files", "--exclude-standard", "tools"]', None, False),
    "no_with_tree": ('["git", "ls-files", "--no-with-tree", "tools"]', None, False),
}

_WRAPPED = {
    "list_concat": ('list(["git"] + ["ls-files", "guide.md"])', '"docs"', True),
    "list_plain": ('list(["git", "ls-files", "guide.md"])', '"docs"', True),
    "tuple_dir": ('tuple(["git", "ls-files", "sub"])', '"docs"', True),
    "list_C_operand": ('list(["git", "-C", "sub"] + ["ls-files", "deep.md"])', '"docs"', True),
    # Not selected: the wrapped argv under its cwd still names no doc.
    "list_tools": ('list(["git", "ls-files", "x.py"])', '"tools"', False),
}


def _call(argv: str, cwd) -> str:
    return argv if cwd is None else f"{argv}, cwd={cwd}"


@pytest.mark.parametrize("name", sorted(_OPTION_ARGS))
def test_an_option_value_is_not_read_as_a_pathspec(name):
    argv, cwd, selected = _OPTION_ARGS[name]
    assert _reasons(_body(_call(argv, cwd))) == (_REASON if selected else []), name


def test_an_option_value_in_a_helper_call_is_skipped_too():
    body = 'def _git(*a):\n    return a\n\n\ndef test_walk():\n    _git("ls-files", "-x", "*.py")\n'
    assert _reasons(body) == _REASON


def test_an_option_value_in_a_C_helper_call_is_skipped_too():
    body = ('def _git(*a):\n    return a\n\n\n'
            'def test_walk():\n    _git("-C", "tools", "ls-files", "--exclude-from", "x.py")\n')
    assert _reasons(body) == _REASON


def test_the_old_reading_still_selects_an_option_value_naming_a_doc():
    # Monotone: before the fix `README.md` was read as a spec and selected;
    # git lists only tools/ here, but the old reading is never dropped.
    assert _reasons(_body('["git", "ls-files", "-x", "README.md", "tools"]')) == _REASON


@pytest.mark.parametrize("name", sorted(_WRAPPED))
def test_cwd_reaches_an_argv_wrapped_in_a_call(name):
    argv, cwd, selected = _WRAPPED[name]
    assert _reasons(_body(_call(argv, cwd))) == (_REASON if selected else []), name


@pytest.mark.parametrize("call", [
    'args=list(["git", "ls-files", "guide.md"]), cwd="docs"',
    'list(["git", "ls-files", "guide.md"]), **kw',
    'list(["git", "ls-files", "guide.md"]), cwd=WHERE',
])
def test_a_wrapped_argv_reads_a_keyword_or_unreadable_cwd(call):
    assert _reasons(_body(call)) == _REASON


def test_a_wrapped_argv_keeps_its_root_reading():
    # Monotone: `:!*.json` under cwd=tools lists tools/x.py only, but the
    # wrapped list's own (root) reading selected before the fix and still does.
    assert _reasons(_body('list(["git", "ls-files", ":!*.json"]), cwd="tools"')) == _REASON


def test_a_none_tracked_md_fails_loud():
    # (c), kept on purpose: None is not "no docs" - reading it as empty would
    # drop every walker without a word.
    with pytest.raises(TypeError):
        mgs.index_walk_reasons(ast.parse(_body('["git", "ls-files"]')), None)


# ---- the git oracle -------------------------------------------------------

def _git_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture(scope="module")
def scratch_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("s144q41") / "repo"
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
    if isinstance(node, ast.Call):
        return _argv_words(node.args[0])
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _argv_words(node.left) + _argv_words(node.right)
    return list(ast.literal_eval(node))


def _git_lists_md(repo: Path, argv: str, cwd) -> bool:
    words = _argv_words(ast.parse(argv, mode="eval").body)
    run_in = repo if cwd is None else repo / ast.literal_eval(cwd)
    out = subprocess.run([_GIT, *words[1:]], cwd=str(run_in), env=_git_env(),
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, (argv, out.stderr)
    return any(line.endswith(".md") for line in out.stdout.splitlines())


@needs_git
@pytest.mark.parametrize("name", sorted(_OPTION_ARGS) + sorted(_WRAPPED))
def test_each_expected_verdict_is_what_git_does(scratch_repo, name):
    argv, cwd, selected = {**_OPTION_ARGS, **_WRAPPED}[name]
    assert _git_lists_md(scratch_repo, argv, cwd) is selected, name
