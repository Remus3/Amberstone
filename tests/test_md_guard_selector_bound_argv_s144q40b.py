"""RM-1146 (2): the docs-guards selector (`tools/md_guard_selector.py`
`index_walk_reasons`) did not tie an argv bound to a NAME to the call that
runs it with `cwd=`:

    cmd = ["git", "ls-files", "guide.md"]
    subprocess.run(cmd, cwd="docs")

lists `docs/guide.md`, but the list was read from the root only (where
`guide.md` matches nothing), so the walker was not selected. The same root
cause covers `args=cmd`, a walrus `run((cmd := [...]), cwd=...)`, a name
wrapped in a call (`list(cmd)`) or used as a `+` operand, a bound `+` chain
and a name aliased to another name.

The fix is an extra reading only (the old ones still select first), and it
never re-reads a binding outside its own scope: a name resolves as Python
resolves it (local, enclosing function, module; a class body is not visible
from its methods; a comprehension target is its own scope; `global` goes to
the module). Each scope case is pinned below both ways.

The verdicts a git run can check are also run through real git in a scratch
repo, so the expected values are git's.
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
_HEAD = "import subprocess\n\n\n"
_DOC = '["git", "ls-files", "guide.md"]'


def _reasons(body: str) -> list:
    return mgs.index_walk_reasons(ast.parse(_HEAD + body), _TRACKED_MD)


# (module body, git oracle key) - each body reaches `git ls-files guide.md`
# (or the oracle's argv) in `docs/` through a binding, so git lists a `.md`.
_SELECTED = {
    "local": (f"def test_w():\n    cmd = {_DOC}\n    subprocess.run(cmd, cwd='docs')\n",
              "guide_in_docs"),
    "module": (f"CMD = {_DOC}\n\n\ndef test_w():\n    subprocess.run(CMD, cwd='docs')\n",
               "guide_in_docs"),
    "module_call_at_module": (f"CMD = {_DOC}\nsubprocess.run(CMD, cwd='docs')\n",
                              "guide_in_docs"),
    "args_keyword": (f"def test_w():\n    cmd = {_DOC}\n"
                     "    subprocess.run(args=cmd, cwd='docs')\n", "guide_in_docs"),
    "bound_chain": ("def test_w():\n    cmd = ['git'] + ['ls-files', 'guide.md']\n"
                    "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "bound_tuple": ("def test_w():\n    cmd = ('git', 'ls-files', 'guide.md')\n"
                    "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "annotated": (f"def test_w():\n    cmd: list = {_DOC}\n"
                  "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "multi_target": (f"def test_w():\n    a = cmd = {_DOC}\n"
                     "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "alias": (f"def test_w():\n    base = {_DOC}\n    cmd = base\n"
              "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "alias_to_module": (f"BASE = {_DOC}\n\n\ndef test_w():\n    cmd = BASE\n"
                        "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "walrus": (f"def test_w():\n    subprocess.run((cmd := {_DOC}), cwd='docs')\n",
               "guide_in_docs"),
    "walrus_in_comprehension": (f"def test_w():\n    [(cmd := {_DOC}) for _ in [1]]\n"
                                "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    # One binding read by two calls in two directories: each is followed.
    "same_name_tools_then_docs": (f"def test_w():\n    cmd = {_DOC}\n"
                                  "    subprocess.run(cmd, cwd='tools')\n"
                                  "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "same_name_docs_then_tools": (f"def test_w():\n    cmd = {_DOC}\n"
                                  "    subprocess.run(cmd, cwd='docs')\n"
                                  "    subprocess.run(cmd, cwd='tools')\n", "guide_in_docs"),
    "type_param_outer_binding": (f"cmd = {_DOC}\n\n\ndef test_w[T]():\n"
                                 "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "nonlocal_from_a_method_binds_the_function": (
        "def test_w():\n    cmd = ['git', 'ls-files', 'tools']\n\n    class C:\n"
        "        cmd = ['git', 'ls-files', 'tools']\n\n        def m(self):\n"
        f"            nonlocal cmd\n            cmd = {_DOC}\n"
        "    C().m()\n    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "type_alias_value_sees_its_class": (
        "cmd = ['git', 'ls-files', 'tools']\n\n\nclass Outer:\n"
        f"    cmd = {_DOC}\n    type A = subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "generic_class_body_reads_module": (
        f"cmd = {_DOC}\n\n\nclass Outer:\n    cmd = ['git', 'ls-files', 'tools']\n\n"
        "    class Inner[T]:\n        subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    # Past _MAX_BASES directories the binding is read in any directory: the
    # `docs` call is never dropped, whichever order the calls are walked in.
    "many_directories": (f"def test_w():\n    cmd = {_DOC}\n"
                         + "".join(f"    subprocess.run(cmd, cwd='tools/d{i}')\n" for i in range(12))
                         + "    subprocess.run(cmd, cwd='docs')\n"
                         + "".join(f"    subprocess.run(cmd, cwd='tools/e{i}')\n" for i in range(12)),
                         "guide_in_docs"),
    "global_value_written_in_a_function": (
        "base = ['git', 'ls-files', 'tools']\n\n\ndef setup():\n    global cmd\n"
        f"    base = {_DOC}\n    cmd = base\n\n\n"
        "def test_w():\n    setup()\n    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    # Round-3 verifier: the any-directory collapse dropped a `..` climb and
    # overwrote the directories recorded before it.
    "dotdot_recorded_before_the_cap": (
        "def test_w():\n    cmd = ['git', 'ls-files', '..']\n    subprocess.run(cmd, cwd='docs')\n"
        + "".join(f"    subprocess.run(cmd, cwd='docs/x{i}')\n" for i in range(12)),
        "dotdot_in_docs"),
    "dotdot_after_the_cap": (
        "def test_w():\n    cmd = ['git', 'ls-files', '..']\n"
        + "".join(f"    subprocess.run(cmd, cwd='tools/x{i}')\n" for i in range(12))
        + "    subprocess.run(cmd, cwd='docs')\n", "dotdot_in_docs"),
    "inner_dotdot_any_directory": (
        "def test_w(d):\n    subprocess.run(['git', 'ls-files', 'sub/../guide.md'], cwd=d)\n",
        "inner_dotdot_in_docs"),
    "wrapped_name": (f"def test_w():\n    cmd = {_DOC}\n"
                     "    subprocess.run(list(cmd), cwd='docs')\n", "guide_in_docs"),
    "bound_wrapped": (f"def test_w():\n    cmd = list({_DOC})\n"
                      "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "name_operand": (f"def test_w():\n    cmd = {_DOC}\n"
                     "    subprocess.run(cmd + ['-t'], cwd='docs')\n", "guide_t_in_docs"),
    "enclosing_function": (f"def test_w():\n    cmd = {_DOC}\n\n    def inner():\n"
                           "        subprocess.run(cmd, cwd='docs')\n    inner()\n",
                           "guide_in_docs"),
    "global_decl": (f"CMD = ['git', 'ls-files', 'tools']\n\n\ndef test_w():\n"
                    f"    global CMD\n    CMD = {_DOC}\n    subprocess.run(CMD, cwd='docs')\n",
                    "guide_in_docs"),
    "global_read": (f"cmd = {_DOC}\n\n\ndef test_w():\n    global cmd\n"
                    "    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "global_assign_read_elsewhere": (f"def setup():\n    global cmd\n    cmd = {_DOC}\n\n\n"
                                     "def test_w():\n    subprocess.run(cmd, cwd='docs')\n",
                                     "guide_in_docs"),
    "nonlocal_assign": ("def test_w():\n    cmd = ['git', 'ls-files', 'tools']\n\n"
                        f"    def inner():\n        nonlocal cmd\n        cmd = {_DOC}\n"
                        "    inner()\n    subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "comprehension_first_iter_reads_outer": (
        f"cmd = {_DOC}\n[cmd for cmd in subprocess.run(cmd, cwd='docs').args]\n",
        "guide_in_docs"),
    "method_reads_module": (f"cmd = {_DOC}\n\n\nclass TestW:\n    def test_w(self):\n"
                            "        subprocess.run(cmd, cwd='docs')\n", "guide_in_docs"),
    "comprehension_reads_enclosing": (
        f"def test_w():\n    cmd = {_DOC}\n"
        "    [subprocess.run(cmd, cwd=d) for d in ['docs']]\n", "guide_in_docs"),
    "path_cwd": (f"from pathlib import Path\nROOT = Path('.')\n\n\ndef test_w():\n"
                 f"    cmd = {_DOC}\n    subprocess.run(cmd, cwd=ROOT / 'docs')\n",
                 "guide_in_docs"),
    "kwargs_cwd": (f"def test_w(**kw):\n    cmd = {_DOC}\n    subprocess.run(cmd, **kw)\n",
                   "guide_in_docs"),
}

# (module body, git oracle key or None) - the binding is NOT the one the call
# reads, or the call's directory holds no `.md`: never selected.
_NOT_SELECTED = {
    "other_function": (f"def helper():\n    cmd = {_DOC}\n\n\ndef test_w():\n"
                       "    subprocess.run(cmd, cwd='docs')\n", None),
    "shadowed_local": (f"cmd = {_DOC}\n\n\ndef test_w():\n"
                       "    cmd = ['git', 'ls-files', 'tools']\n"
                       "    subprocess.run(cmd, cwd='docs')\n", "tools_in_docs"),
    "parameter": (f"cmd = {_DOC}\n\n\ndef test_w(cmd):\n    subprocess.run(cmd, cwd='docs')\n",
                  None),
    "class_body_not_visible": (f"class TestW:\n    cmd = {_DOC}\n\n    def test_w(self):\n"
                               "        subprocess.run(cmd, cwd='docs')\n", None),
    "comprehension_target": (f"cmd = {_DOC}\n"
                             "[subprocess.run(cmd, cwd='docs') for cmd in [['git', 'ls-files',"
                             " 'tools']]]\n", "tools_in_docs"),
    "lambda_parameter": (f"cmd = {_DOC}\nrun = lambda cmd: subprocess.run(cmd, cwd='docs')\n",
                         None),
    "nested_function_own_binding": (f"def test_w():\n    def inner():\n        cmd = {_DOC}\n"
                                    "        return cmd\n    subprocess.run(cmd, cwd='docs')\n",
                                    None),
    "import_shadow": (f"cmd = {_DOC}\n\n\ndef test_w():\n    from os import sep as cmd\n"
                      "    subprocess.run(cmd, cwd='docs')\n", None),
    "except_shadow": (f"cmd = {_DOC}\n\n\ndef test_w():\n    try:\n        pass\n"
                      "    except OSError as cmd:\n        subprocess.run(cmd, cwd='docs')\n", None),
    # Found by the round-1 verifier: each read the module binding.
    "match_capture": (f"cmd = {_DOC}\n\n\ndef test_w(x):\n    match x:\n        case cmd:\n"
                      "            pass\n    subprocess.run(cmd, cwd='docs')\n", None),
    "match_star": (f"cmd = {_DOC}\n\n\ndef test_w(x):\n    match x:\n        case [*cmd]:\n"
                   "            pass\n    subprocess.run(cmd, cwd='docs')\n", None),
    "match_mapping_rest": (f"cmd = {_DOC}\n\n\ndef test_w(x):\n    match x:\n"
                           "        case {'k': 1, **cmd}:\n            pass\n"
                           "    subprocess.run(cmd, cwd='docs')\n", None),
    "class_global_not_for_methods": (
        f"cmd = {_DOC}\n\n\ndef test_w():\n    cmd = ['git', 'ls-files', 'tools']\n\n"
        "    class C:\n        global cmd\n\n        def m(self):\n"
        "            subprocess.run(cmd, cwd='docs')\n", "tools_in_docs"),
    "type_param_function": (f"cmd = {_DOC}\n\n\ndef test_w[cmd]():\n"
                            "    subprocess.run(cmd, cwd='docs')\n", None),
    "type_param_class_method": (f"cmd = {_DOC}\n\n\nclass TestW[cmd]:\n    def test_w(self):\n"
                                "        subprocess.run(cmd, cwd='docs')\n", None),
    # Found by the round-2 verifier.
    "nonlocal_skips_class": (
        f"cmd = {_DOC}\n\n\ndef test_w():\n    class C:\n"
        "        cmd = ['git', 'ls-files', 'tools']\n\n        def m(self):\n"
        f"            nonlocal cmd\n            cmd = {_DOC}\n"
        "        subprocess.run(cmd, cwd='docs')\n    cmd = None\n", "tools_in_docs"),
    "type_alias_param": (f"cmd = {_DOC}\ntype X[cmd] = subprocess.run(cmd, cwd='docs')\n", None),
    "annotation_scope_sees_its_class": (
        f"cmd = {_DOC}\n\n\nclass Outer:\n    cmd = ['git', 'ls-files', 'tools']\n\n"
        "    class Inner[T]((subprocess.run(cmd, cwd='docs'), dict)[1]):\n        pass\n",
        "tools_in_docs"),
    # Found by the round-3 verifier: a value is read where it is written.
    "global_value_read_where_written": (
        f"base = {_DOC}\n\n\ndef setup():\n    global cmd\n"
        "    base = ['git', 'ls-files', 'tools']\n    cmd = base\n\n\n"
        "def test_w():\n    setup()\n    subprocess.run(cmd, cwd='docs')\n", "tools_in_docs"),
    "nonlocal_value_read_where_written": (
        f"base = {_DOC}\n\n\ndef test_w():\n    cmd = None\n\n    def inner():\n"
        "        nonlocal cmd\n        base = ['git', 'ls-files', 'tools']\n        cmd = base\n"
        "    inner()\n    subprocess.run(cmd, cwd='docs')\n", "tools_in_docs"),
    "walrus_value_read_in_its_comprehension": (
        f"def test_w():\n    c = {_DOC}\n"
        "    [(cmd := c) for c in [['git', 'ls-files', 'tools']]]\n"
        "    subprocess.run(cmd, cwd='docs')\n", "tools_in_docs"),
    "no_md_under_cwd": (f"def test_w():\n    cmd = {_DOC}\n    subprocess.run(cmd, cwd='tools')\n",
                        "guide_in_tools"),
    "root_cwd": (f"def test_w():\n    cmd = {_DOC}\n    subprocess.run(cmd)\n", "guide_at_root"),
}


@pytest.mark.parametrize("name", sorted(_SELECTED))
def test_cwd_reaches_an_argv_bound_to_a_name(name):
    body, _ = _SELECTED[name]
    assert _reasons(body) == _REASON, name


@pytest.mark.parametrize("name", sorted(_NOT_SELECTED))
def test_a_binding_is_never_read_outside_its_own_scope(name):
    body, _ = _NOT_SELECTED[name]
    assert _reasons(body) == [], name


def test_the_root_reading_of_a_bound_argv_still_selects():
    # Monotone: a bound argv that reaches a `.md` from the root is selected
    # with or without the call's `cwd=`.
    body = "def test_w():\n    cmd = ['git', 'ls-files', 'docs']\n    subprocess.run(cmd, cwd='tools')\n"
    assert _reasons(body) == _REASON


def test_an_alias_cycle_terminates():
    body = "def test_w():\n    a = b\n    b = a\n    subprocess.run(a, cwd='docs')\n"
    assert _reasons(body) == []


def test_a_deep_alias_chain_is_followed_to_its_end():
    # Iterative, so no RecursionError, and no hop cap drops the far end.
    names = [f"n{i}" for i in range(400)]
    lines = [f"    {names[0]} = {_DOC}"]
    lines += [f"    {b} = {a}" for a, b in zip(names, names[1:])]
    body = "def test_w():\n" + "\n".join(lines) + f"\n    subprocess.run({names[-1]}, cwd='docs')\n"
    assert _reasons(body) == _REASON


def test_many_calls_reading_one_name_mark_each_literal_once():
    # Round-1 verifier: 6000 `run(cmd, cwd=...)` calls walked the binding
    # list once per call (quadratic). The walk is now once per (binding,
    # directory); that cost is measured in the cycle report, not pinned here
    # (a wall-clock budget would flake). This pins the result shape only.
    calls = "".join(f"    cmd = ['git', 'ls-files', 'n{i}.txt']\n" for i in range(300))
    calls += "".join("    subprocess.run(cmd, cwd='docs')\n" for _ in range(300))
    body = "def test_w():\n" + calls
    bound = mgs._bound_argv_bases(ast.parse(_HEAD + body), {})
    assert len(bound) == 300
    assert all(bases == ["docs"] for bases in bound.values())


def test_many_directories_collapse_to_the_widest_reading():
    # Round-2 verifier: N calls in N directories gave every bound literal N
    # readings. Past _MAX_BASES the literal is also read in any directory
    # (None) and records no more; the directories before the cap are kept
    # (round-3 verifier: overwriting them lost a `..` climb).
    calls = "".join(f"    subprocess.run(cmd, cwd='d{i}')\n" for i in range(40))
    body = f"def test_w():\n    cmd = {_DOC}\n" + calls
    (bases,) = mgs._bound_argv_bases(ast.parse(_HEAD + body), {}).values()
    assert len(bases) == mgs._MAX_BASES + 1 and bases[-1] is None
    assert all(isinstance(base, str) for base in bases[:-1])


# ---- the git oracle -------------------------------------------------------

_ORACLE = {
    "guide_in_docs": (["ls-files", "guide.md"], "docs", True),
    "guide_t_in_docs": (["ls-files", "guide.md", "-t"], "docs", True),
    "tools_in_docs": (["ls-files", "tools"], "docs", False),
    "guide_in_tools": (["ls-files", "guide.md"], "tools", False),
    "guide_at_root": (["ls-files", "guide.md"], None, False),
    "dotdot_in_docs": (["ls-files", ".."], "docs", True),
    "inner_dotdot_in_docs": (["ls-files", "sub/../guide.md"], "docs", True),
}


@pytest.mark.parametrize("spec, expected", [
    ("..", "."), ("../..", "."), ("../README.md", "README.md"), ("sub/../guide.md", "guide.md"),
    ("a/./b.md", "a/b.md"), ("..\\x.md", "x.md"), ("docs", "docs"), (".", "."),
])
def test_climb_free(spec, expected):
    assert mgs._climb_free(spec) == expected


def test_the_any_directory_reading_covers_each_directory():
    # The premise of the collapse: for every spec and directory, the None
    # reading selects whenever that directory's reading does. Plain
    # directories only: a base holding a glob character (`[d]`) is read by
    # fnmatch as a glob, a spurious match git never makes, which the None
    # reading need not repeat (round-4 verifier, measured against git).
    suffixes = mgs._md_suffix_index(_TRACKED_MD)
    specs = ["..", "../..", "../README.md", "sub/../guide.md", "guide.md", "sub", "*.md",
             "../*.md", "sub/*.md", ".", "../docs", "x/../sub/deep.md", "./guide.md"]
    for base in ("", "docs", "docs/sub", "tools", "tools/x"):
        for spec in specs:
            if mgs._md_pathspec_in(spec, base, _TRACKED_MD, suffixes):
                assert mgs._md_pathspec_in(spec, None, _TRACKED_MD, suffixes), (spec, base)


def _git_env() -> dict:
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


@pytest.fixture(scope="module")
def scratch_repo(tmp_path_factory) -> Path:
    repo = tmp_path_factory.mktemp("s144q40b") / "repo"
    files = {
        "README.md": b"# r\n", "docs/guide.md": b"# g\n", "docs/sub/deep.md": b"# d\n",
        "tools/x.py": b"x = 1\n",
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


@needs_git
@pytest.mark.parametrize("key", sorted(_ORACLE))
def test_each_oracle_verdict_is_what_git_does(scratch_repo, key):
    words, cwd, lists_md = _ORACLE[key]
    run_in = scratch_repo if cwd is None else scratch_repo / cwd
    out = subprocess.run([_GIT, *words], cwd=str(run_in), env=_git_env(),
                         capture_output=True, text=True, timeout=60, check=False)
    assert out.returncode == 0, (key, out.stderr)
    assert any(line.endswith(".md") for line in out.stdout.splitlines()) is lists_md, key


def test_every_case_names_an_oracle_that_agrees_with_it():
    for name, (_, key) in _SELECTED.items():
        assert _ORACLE[key][2] is True, name
    for name, (_, key) in _NOT_SELECTED.items():
        assert key is None or _ORACLE[key][2] is False, name
