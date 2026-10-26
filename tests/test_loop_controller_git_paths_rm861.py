"""RM-861 (ops/loop/loop_controller.py site): the auditor reads changed paths as themselves.

`auditor()` builds the REGRESS / CLEAN prompt from three `git diff` reads taken
through `git()`, which decoded through the locale (`text=True`) and left git's
default core.quotePath on:

- `--name-status` (the FILES CHANGED manifest, the "complete + authoritative"
  list) and the diff body named a non-ASCII path C-quoted
  (`"caf\\303\\251.../x.md"`), so the auditor was handed an escape string, not
  the file the commit touched.
- `--name-only` was split with `.splitlines()`, so a raw name carrying U+2028
  counted as two files in the "N total" line.
- Outside UTF-8 mode the locale decode (cp1252 on Windows) turned UTF-8 bytes
  in the diff body or a commit subject into mojibake, and a byte cp1252 leaves
  undefined (0x81 in "A-acute") killed subprocess's reader thread with a
  UnicodeDecodeError: stdout came back None, `.strip()` raised AttributeError
  (not a SubprocessError / OSError, so it was not degraded to "") and the
  cycle's audit crashed.

Fix: `git()` decodes UTF-8 with errors="replace"; the auditor's path reads run
under `-c core.quotepath=false`, and the count reads `--name-only -z`.

Every repo here is a throwaway under tmp_path with git's global config pinned
to an empty file, the system config off and `GIT_CONFIG_COUNT` cleared, so no
host-wide setting decides the result. Source stays ASCII: every non-ASCII probe
is built with chr().
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CTRL = _ROOT / "ops" / "loop" / "loop_controller.py"

_DIR = "caf" + chr(0x00E9) + chr(0x0101)
_DOC = _DIR + "/rm861-audit.md"
# U+00C1 is C3 81 in UTF-8; 0x81 is undefined in cp1252, so a locale decode raises.
_LINE = "rm861 body " + chr(0x00C1) + chr(0x00E9)
_SUBJECT = "rm861 subject " + chr(0x00C1)


@pytest.fixture(scope="module")
def lc():
    spec = importlib.util.spec_from_file_location("_rm861_loop_controller", _CTRL)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def git_env(tmp_path, monkeypatch):
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("", encoding="ascii")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for key in list(os.environ):
        if key == "GIT_CONFIG_COUNT" or key.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")):
            monkeypatch.delenv(key, raising=False)
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.delenv(key, raising=False)
    return dict(os.environ)


def _repo(tmp_path: Path, env: dict, files: list[str], quotepath: str = "true") -> dict:
    repo = tmp_path / "repo"
    repo.mkdir()

    def run(*args) -> str:
        out = subprocess.run(["git", *args], cwd=repo, capture_output=True, env=env, check=True)
        return out.stdout.decode("utf-8").strip()

    run("init", "-q", ".")
    run("config", "user.email", "rm861@test")
    run("config", "user.name", "rm861")
    run("config", "core.quotepath", quotepath)
    run("config", "core.autocrlf", "false")
    (repo / "ops" / "loop").mkdir(parents=True)
    (repo / "ops" / "loop" / "auditor_prompt.md").write_bytes(b"AUDIT PROMPT\n")
    (repo / "base.txt").write_bytes(b"base\n")
    run("add", "-A")
    run("commit", "-q", "-m", "base")
    c0 = run("rev-parse", "HEAD")
    for rel in files:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes((_LINE + "\n").encode("utf-8"))
    run("add", "-A")
    run("commit", "-q", "-m", _SUBJECT)
    return {"root": repo, "c0": c0, "head": run("rev-parse", "HEAD")}


def _audit_body(lc, monkeypatch, tmp_path: Path, r: dict) -> str:
    captured: dict = {}

    def _capture(body, _instruction):
        captured["body"] = body
        return "VERDICT: CLEAN"

    monkeypatch.setattr(lc, "ROOT", r["root"])
    monkeypatch.setattr(lc, "CTL", tmp_path)
    monkeypatch.setattr(lc, "log", lambda _m: None)
    monkeypatch.setattr(lc, "adjudicate", _capture)
    lc.auditor(r["c0"], r["head"])
    return captured["body"]


def _manifest(body: str) -> str:
    return body.split("=== FILES CHANGED", 1)[1].split("=== DIFF", 1)[0]


def test_control_ascii_path_is_named_in_the_manifest(tmp_path, git_env, lc, monkeypatch):
    r = _repo(tmp_path, git_env, ["docs/rm861-audit.md"])
    body = _audit_body(lc, monkeypatch, tmp_path, r)
    assert "(1 total;" in body
    assert "docs/rm861-audit.md" in _manifest(body)


def test_a_non_ascii_path_is_named_as_itself(tmp_path, git_env, lc, monkeypatch):
    """Quoted, the manifest and the diff header carried `"caf\\303\\251..."`."""
    r = _repo(tmp_path, git_env, [_DOC])
    body = _audit_body(lc, monkeypatch, tmp_path, r)
    assert _DOC in _manifest(body), _manifest(body)
    assert "\\303" not in body
    diff_part = body.split("=== DIFF", 1)[1]
    assert "+++ b/" + _DOC in diff_part


def test_a_name_with_a_unicode_line_separator_counts_once(tmp_path, git_env, lc, monkeypatch):
    """U+2028 is a line break to str.splitlines(), never to `--name-only -z`."""
    rel = "x" + chr(0x2028) + "y/rm861-audit.md"
    try:
        r = _repo(tmp_path, git_env, [rel], quotepath="false")
    except OSError:
        pytest.skip("filesystem refuses a U+2028 file name")
    body = _audit_body(lc, monkeypatch, tmp_path, r)
    assert "(1 total;" in body, _manifest(body)


def test_the_audit_survives_a_non_utf8_locale(tmp_path, git_env):
    """A child outside UTF-8 mode: the decode must not be the locale's, and must not raise."""
    r = _repo(tmp_path, git_env, [_DOC])
    ctl = tmp_path / "ctl"
    ctl.mkdir()
    code = (
        "import importlib.util, json, sys\n"
        "from pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('lc', sys.argv[1])\n"
        "mod = importlib.util.module_from_spec(spec)\n"
        "sys.modules['lc'] = mod\n"
        "spec.loader.exec_module(mod)\n"
        "mod.ROOT = Path(sys.argv[2])\n"
        "mod.CTL = Path(sys.argv[3])\n"
        "mod.log = lambda _m: None\n"
        "seen = {}\n"
        "def _capture(body, _instruction):\n"
        "    seen['body'] = body\n"
        "    return 'VERDICT: CLEAN'\n"
        "mod.adjudicate = _capture\n"
        "mod.auditor(sys.argv[4], sys.argv[5])\n"
        "print(json.dumps({'body': seen.get('body', '')}))\n"
    )
    env = {k: v for k, v in git_env.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
    env["PYTHONIOENCODING"] = "ascii:backslashreplace"
    # POSIX: a C locale without PEP 538 coercion makes the locale codec ASCII.
    env["LC_ALL"] = "C"
    env["PYTHONCOERCECLOCALE"] = "0"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.run(
        [sys.executable, "-X", "utf8=0", "-c", code, str(_CTRL), str(r["root"]), str(ctl),
         r["c0"], r["head"]],
        capture_output=True, env=env, creationflags=flags, check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    body = json.loads(proc.stdout.decode("ascii").strip().splitlines()[-1])["body"]
    assert _DOC in _manifest(body)
    assert "+" + _LINE in body
    assert _SUBJECT in body
