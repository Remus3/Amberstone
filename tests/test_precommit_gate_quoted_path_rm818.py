"""RM-818 verifier N2: the commit gate never linted a non-ASCII-named file.

`git diff --cached` writes a path holding a byte over 0x7F in its QUOTED form
(core.quotePath, on by default): `+++ "b/d\\304\\201.py"`. tools/precommit_gate.py
keyed that header text as the path, so the key ended in `.py"`, the file
never reached ruff, and a staged d<U+0101>.py with an unused import passed
with exit 0. Every git call in the gate now runs with -c core.quotepath=false,
so the header carries the real name.

The repo is a throwaway under tmp_path, with git's global config pinned to an
empty file and the system config off, so a host-wide quotepath setting cannot
decide the result. No ruff.toml: ruff's default rules include F401.

Source stays ASCII: every non-ASCII probe is built with chr().
"""
from __future__ import annotations

import ast
import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "tools"))

import precommit_gate as G  # noqa: E402

from tests._module_view import bind_subprocess  # noqa: E402

_A_MACRON = chr(0x0101)
requires_ruff = pytest.mark.skipif(
    importlib.util.find_spec("ruff") is None, reason="ruff is not importable by this interpreter"
)


# RM-829 (d): config can also arrive through the environment - GIT_CONFIG_COUNT
# with its KEY_<n> / VALUE_<n> pairs, and GIT_CONFIG_PARAMETERS (how `git -c`
# reaches a child) - so an inherited core.quotepath there could decide the
# result too. The fixture clears both, in this process and in the child env.
_ENV_CONFIG = ("GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS")


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in _ENV_CONFIG:
        monkeypatch.delenv(name, raising=False)
    return {**os.environ}


@pytest.fixture
def injected_quotepath(monkeypatch):
    """Env-injected `core.quotepath=true`, set BEFORE git_env runs."""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.quotepath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'core.quotepath'='true'")


def test_the_git_env_clears_env_injected_config(injected_quotepath, git_env):
    for name in _ENV_CONFIG:
        assert name not in git_env, name
        assert name not in os.environ, name


def _staged(tmp_path: Path, env: dict, name: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args):
        subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)

    run("init", "-q", ".")
    run("config", "user.email", "gate@test")
    run("config", "user.name", "gate")
    (repo / "base.txt").write_text("base\n", encoding="ascii")
    run("add", "-A")
    run("commit", "-qm", "base")
    (repo / name).write_text("import os\n", encoding="ascii")
    run("add", "-A")
    return repo


def _gate(monkeypatch, capsys, repo: Path):
    monkeypatch.chdir(repo)
    monkeypatch.setattr("sys.stdin", io.StringIO("git commit"))
    rc = G.main()
    return rc, capsys.readouterr().err


def test_the_staged_diff_keys_a_non_ascii_path_by_its_real_name(tmp_path, git_env):
    name = "d" + _A_MACRON + ".py"
    repo = _staged(tmp_path, git_env, name)
    assert sorted(G._staged_added(str(repo))) == [name]
    assert G._staged_new_paths(str(repo)) == [name]


@requires_ruff
@pytest.mark.parametrize("name", ["d" + _A_MACRON + ".py", "d.py"])
def test_a_staged_unused_import_blocks_whatever_the_file_is_called(
        name, tmp_path, git_env, monkeypatch, capsys):
    repo = _staged(tmp_path, git_env, name)
    rc, err = _gate(monkeypatch, capsys, repo)
    assert rc == 2, (rc, err[-1500:])
    assert "F401" in err, err[-1500:]


def test_every_git_call_turns_quotepath_off(tmp_path, git_env, monkeypatch):
    seen = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))

        class _P:
            stdout, stderr, returncode = "", "", 0
        return _P()

    bind_subprocess(monkeypatch, G, run=fake_run)
    G._git(["diff", "--cached", "--unified=0"], str(tmp_path))
    G._git(["diff", "--cached", "--name-status", "-z"], str(tmp_path))
    assert seen and all(argv[:3] == ["git", "-c", "core.quotepath=false"] for argv in seen), seen


# RM-829 (e): the test above drives _git directly, so a git call written
# around _GIT would pass it. The two below cover every subprocess call in the
# gate: a source census of each call site, and a whole main() run recorded.
_SUBPROCESS_CALLS = {"run", "Popen", "call", "check_call", "check_output",
                     "getoutput", "getstatusoutput"}


def _subprocess_sites():
    tree = ast.parse(Path(G.__file__).read_text(encoding="utf-8"))
    sites = []
    for func in ast.walk(tree):
        if not isinstance(func, ast.FunctionDef):
            continue
        for node in ast.walk(func):
            callee = getattr(node, "func", None)
            if not (isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name)):
                continue
            owner, name = callee.value.id, callee.attr
            if (owner == "subprocess" and name in _SUBPROCESS_CALLS) or (
                    owner == "os" and (name in {"system", "popen"} or name.startswith("spawn"))):
                sites.append((func.name, owner + "." + name, node))
    return sites


def _argv_head(node):
    """`[*NAME, ...]` -> NAME, `["lit", ...]` -> 'lit', anything else -> None."""
    argv = node.args[0] if node.args else None
    if not (isinstance(argv, ast.List) and argv.elts):
        return None
    first = argv.elts[0]
    if isinstance(first, ast.Starred) and isinstance(first.value, ast.Name):
        return "*" + first.value.id
    if isinstance(first, ast.Constant):
        return repr(first.value)
    return None


def test_every_subprocess_call_site_in_the_gate_is_accounted_for():
    """A new call site fails here until it is classified: git goes through
    _GIT, and the only other children are the resolved ruff command."""
    sites = sorted((fn, call, _argv_head(node)) for fn, call, node in _subprocess_sites())
    assert sites == [
        ("_gate_commit", "subprocess.run", "*ruff"),
        ("_git", "subprocess.run", "*_GIT"),
        ("_resolve_ruff", "subprocess.run", "*cmd"),
    ], sites


@requires_ruff
def test_a_whole_gate_run_sends_every_git_call_through_quotepath_off(
        tmp_path, git_env, monkeypatch, capsys):
    repo = _staged(tmp_path, git_env, "d" + _A_MACRON + ".py")
    real_run, seen = subprocess.run, []

    def recording_run(argv, *args, **kwargs):
        seen.append([str(part) for part in argv])
        return real_run(argv, *args, **kwargs)

    bind_subprocess(monkeypatch, G, run=recording_run)
    rc, err = _gate(monkeypatch, capsys, repo)
    assert rc == 2, (rc, err[-1500:])
    gits = [argv for argv in seen if Path(argv[0]).stem.lower() == "git"]
    others = [argv for argv in seen if Path(argv[0]).stem.lower() != "git"]
    assert len(gits) >= 2 and others, seen
    assert all(argv[:3] == G._GIT for argv in gits), gits
    assert all("ruff" in " ".join(argv) for argv in others), others
